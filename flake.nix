{
  description = "Echo AI - Rust development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    # Provides exact-pin rust toolchains (stable + nightly) inside nix,
    # matching rust-toolchain.toml. Toolchain versions are fixed by the
    # committed flake.lock snapshot; do not run `nix flake update` casually.
    rust-overlay.url = "github:oxalica/rust-overlay";
  };

  outputs = { self, nixpkgs, flake-utils, rust-overlay }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ rust-overlay.overlays.default ];
        };

        # Stable toolchain: must match rust-toolchain.toml exactly
        # (fromRustupToolchainFile reads the file, so the two cannot drift).
        stable = pkgs.rust-bin.fromRustupToolchainFile ./rust-toolchain.toml;

        # Nightly toolchain for the sanitizer (ASan/UBSan/TSan, via
        # -Z build-std) and Miri stages. Pinned date; component list mirrors
        # what CI's sanitizer stages invoke. `miri` is a rustup component
        # on nightly, not a separate package.
        nightly = pkgs.rust-bin.nightly."2026-08-25".default.override {
          extensions = [ "rust-src" "llvm-tools-preview" "miri" ];
        };
      in
      {
        packages.default = pkgs.rustPlatform.buildRustPackage {
          pname = "echo-ai";
          version = "0.1.0";
          src = ./.;
          cargoLock.lockFile = ./Cargo.lock;
          buildAndTestSubdir = "crates/echo-ai";
          # The server embeds no frontend build; the dist directory is
          # copied as-is (pure static files, no node build step).
          preBuild = ''
            mkdir -p frontend
            cp -r frontend/dist frontend/dist
          '';
          installPhase = ''
            runHook preInstall
            mkdir -p $out/bin $out/share/man/man1 $out/share/echo-ai
            cp target/release/echo-ai $out/bin/echo-ai
            cp man/echo-ai.1 $out/share/man/man1/echo-ai.1
            cp -r frontend/dist $out/share/echo-ai/frontend
            runHook postInstall
          '';
          meta = {
            description = "Agentic AI assistant with web and terminal UIs";
            license = pkgs.lib.licenses.mit;
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/echo-ai";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # rust-overlay's rustup shim FIRST so its cargo/rustc proxies
            # take PATH precedence over the direct toolchain binaries
            # below — that is what makes `cargo +nightly` dispatch work.
            rustup
            stable
            nightly

            # Toolchain-adjacent tooling used by CI and the dev workflow
            # (all versions floating; the rules that matter are pinned by
            # rust-toolchain.toml / flake.lock).
            cargo-nextest # recommended test runner (AGENTS.md "Testing")
            cargo-audit   # dependency vulnerability gate (CI)
            cargo-deny    # license + duplicate-dependency gate (CI)
            cargo-fuzz    # libFuzzer targets for external-input parsers
            cargo-llvm-cov # coverage, optional
            rust-analyzer # LSP for editors

            # Build-time requirements of the dependency tree:
            # rusqlite "bundled" compiles sqlite3 from source via `cc`,
            # and ring (rustls) needs a C compiler too.
            gcc
            python3 # the python_execute tool runs scripts in the workspace
            # node is only needed for the frontend build (Phase 7); kept in
            # the shell so `npm ci && npm run build` works without leaving
            # nix develop.
            nodejs_22

            # Optional runtime companions, same policy as the C flake:
            # the browser tool spawns whichever Chromium-family binary it
            # discovers at runtime, so no browser is pinned here.
          ];

          shellHook = ''
            # Point the rustup shim's "nightly" toolchain at the nix-built
            # one via a direct symlink. (The shim's own `toolchain link`
            # COPIES the store path and drops extension components like
            # cargo-miri and rust-src — unacceptable, so we bypass it.)
            # Idempotent: a fresh symlink replaces any stale copy.
            rm -rf "$HOME/.rustup/toolchains/nightly-x86_64-unknown-linux-gnu"
            ln -s ${nightly} "$HOME/.rustup/toolchains/nightly-x86_64-unknown-linux-gnu"
            echo "Echo AI Rust dev environment ready"
            echo "  stable:  $(cargo --version)"
            echo "  nightly: $(rustc +nightly --version 2>/dev/null || echo 'not linked')"
            echo "  miri:    $(cargo +nightly miri --version 2>/dev/null || echo 'not installed')"
          '';
        };
      });
}