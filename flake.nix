{
  description = "Agent Framework - Full stack AI agent platform";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, pyproject-nix, uv2nix, pyproject-build-systems }:
    let
      inherit (nixpkgs) lib;
    in
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        # Load uv workspace from uv.lock
        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

        # Create an overlay that provides all Python dependencies from uv.lock
        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        # Python package set with pyproject-nix build infrastructure + uv2nix deps
        basePython = pkgs.python312;
        pythonSetBase = (pkgs.callPackage pyproject-nix.build.packages {
          python = basePython;
        }).overrideScope (lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          overlay
        ]);

        # Override agentframework with custom postPatch/postInstall
        pythonSet = pythonSetBase.overrideScope (final: prev: {
          agentframework = prev.agentframework.overrideAttrs (old: {
            postPatch = (old.postPatch or "") + ''
              find src -name "*.py" -exec sed -i {} \
                -e 's/from src\.agentframework/from agentframework/g' \
                -e 's/import src\.agentframework/import agentframework/g' \
                -e 's/from src\.workflows/from workflows/g' \
                -e 's/import src\.workflows/import workflows/g' \;
            '';

            postInstall = (old.postInstall or "") + ''
              cp -r src/workflows $out/${prev.python.sitePackages}/
            '';
          });
        });

        # Build a virtualenv that includes agentframework and all its dependencies
        agentframeworkEnv = pythonSet.mkVirtualEnv "agentframework-env" workspace.deps.default;

        frontend = pkgs.buildNpmPackage {
          pname = "agentframework-frontend";
          version = "0.0.0";
          src = ./frontend;

          npmDepsHash = "sha256-gLPK9CBv0UBORgYPsgWertCfvBaEk/xP2W5WqbzB8JM=";

          npmBuildScript = "build";

          installPhase = ''
            runHook preInstall
            mkdir -p $out/share/frontend
            cp -r dist/* $out/share/frontend/
            runHook postInstall
          '';
        };

        server-script = pkgs.writeText "serve_fullstack.py" ''
          import os
          from agentframework.web_api import app
          from fastapi.staticfiles import StaticFiles
          from fastapi.responses import FileResponse

          frontend_dir = os.environ.get("AGENT_FRONTEND_DIR")

          if os.path.isdir(frontend_dir):
              for i, route in enumerate(app.routes):
                  if hasattr(route, 'path') and route.path == '/':
                      app.routes.pop(i)
                      break

              app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

              @app.get("/")
              async def serve_index():
                  return FileResponse(os.path.join(frontend_dir, "index.html"))

              @app.get("/{path:path}")
              async def serve_spa(path: str):
                  file_path = os.path.join(frontend_dir, path)
                  if os.path.isfile(file_path):
                      return FileResponse(file_path)
                  return FileResponse(os.path.join(frontend_dir, "index.html"))

          import uvicorn
          port = int(os.environ.get("AGENT_WEB_PORT", "8080"))
          uvicorn.run(app, host="0.0.0.0", port=port)
        '';

        combined = pkgs.stdenv.mkDerivation {
          pname = "agentframework-fullstack";
          version = "0.1.0";
          src = ./.;

          installPhase = ''
            mkdir -p $out/bin
            mkdir -p $out/share/agentframework/frontend

            cp -r ${frontend}/share/frontend/* $out/share/agentframework/frontend/

            mkdir -p $out/libexec
            cat > $out/libexec/serve-wrapper.sh << 'WRAPEOF'
            #!/bin/bash
            set -e

            export AGENT_FRONTEND_DIR="__FRONTEND_DIR__"
            export ECHO_SESSION_DIR="''${HOME}/.echo-ai/sessions"
            mkdir -p "''${HOME}/.echo-ai/sessions"

            ENV_FILE="''${HOME}/.echo-ai/.env"
            if [ -f "$ENV_FILE" ]; then
                while IFS='=' read -r key value; do
                    case "$key" in
                        \#*|"") continue ;;
                        *) export "$key=$value" ;;
                    esac
                done < "$ENV_FILE"
            fi

            export PYTHONNOUSERSITE=true
            export PYTHONPATH="__PYTHONPATH__"
            exec __PYTHON__ __SERVER_SCRIPT__
            WRAPEOF

            sed -i $out/libexec/serve-wrapper.sh \
              -e "s|__FRONTEND_DIR__|$out/share/agentframework/frontend|g" \
              -e "s|__PYTHONPATH__|${agentframeworkEnv}/${basePython.sitePackages}|g" \
              -e "s|__PYTHON__|${agentframeworkEnv}/bin/python|g" \
              -e "s|__SERVER_SCRIPT__|${server-script}|g"

            cp $out/libexec/serve-wrapper.sh $out/bin/agent-web
            chmod +x $out/bin/agent-web
          '';
        };

        devShell = pkgs.mkShell {
          packages = [
            pythonSet.python
            pythonSet.python.pkgs.pip
            pkgs.uv
            pkgs.nodejs_22
            pkgs.pre-commit
            pkgs.ruff
            pkgs.pyright
            pkgs.nixpkgs-fmt
            pkgs.gnumake
            pkgs.sqlite
            pkgs.mkdocs
            pkgs.git
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
            pkgs.libgcc
            pkgs.glibc
            pkgs.lz4
            pkgs.openssl
          ];
          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
            pkgs.stdenv.cc.cc.lib
            pkgs.zlib
            pkgs.libgcc
            pkgs.glibc
            pkgs.lz4
            pkgs.openssl
          ];

          shellHook = ''
            export PYTHONPATH=$PWD/src
            if [ -f "$HOME/.echo-ai/.env" ]; then
                set -a
                source "$HOME/.echo-ai/.env"
                set +a
            fi

            echo "Syncing backend dependencies..."
            uv sync --extra dev --extra otel --extra ui --extra web-scraping

            echo ""
            echo "Agent Framework dev environment ready"
            echo "  Backend:  uv sync (synced automatically on entry)"
            echo "  Frontend: cd frontend && npm install"
            echo "  Config:   ~/.echo-ai/config.yaml"
            echo "  Nix Ops:"
            echo "    Build fullstack:  nix build"
            echo "    Run fullstack:    nix run ."
          '';
        };

      in
      {
        packages = {
          default = combined;
          backend = pythonSet.agentframework;
          frontend = frontend;
          fullstack = combined;
        };

        formatter = pkgs.nixpkgs-fmt;

        devShells.default = devShell;

        apps.default = {
          type = "app";
          program = "${combined}/bin/agent-web";
        };

        checks = {
          backend = pythonSet.agentframework;
          frontend-pkg = frontend;
          fullstack = combined;
        };
      }
    );
}
