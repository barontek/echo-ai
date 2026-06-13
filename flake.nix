{
  description = "Agent Framework - Full stack AI agent platform";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };

        python = pkgs.python312;

        tavily = python.pkgs.buildPythonPackage rec {
          pname = "tavily";
          version = "0.3.3";

          # The actual PyPI package is named tavily-python but imports as tavily
          src = python.pkgs.fetchPypi {
            pname = "tavily-python";
            inherit version;
            sha256 = "sha256-FKw9DLXSzgVIfn6AIEYM17iNg8mRb0bjRLzyVXes00Y=";
          };

          format = "setuptools";

          propagatedBuildInputs = with python.pkgs; [
            httpx
            requests
            tiktoken
          ];

          # Skip the runtime deps check since wheel metadata says "tavily-python"
          # but we expose it as "tavily"
          pythonCatchConflictsPhase = "";
        };

        agentframework = python.pkgs.buildPythonPackage rec {
          pname = "agentframework";
          version = "0.1.0";
          src = ./.;

          format = "pyproject";

          pythonRelaxDeps = true;

          # Skip runtime deps check - we handle deps manually
          dontCheckRuntimeDeps = true;

          nativeBuildInputs = with python.pkgs; [
            hatchling
          ];

          propagatedBuildInputs = with python.pkgs; [
            anthropic
            openai
            httpx
            pyyaml
            rich
            beautifulsoup4
            prompt-toolkit
            aiohttp
            pydantic
            tenacity
            sqlalchemy
            aiosqlite
            greenlet
            fastapi
            uvicorn
            websockets
            markdown
            sentry-sdk
            tiktoken
            charset-normalizer
            chardet
            markdownify
            urllib3
          ] ++ [
            tavily
          ] ++ [
            # Not available in nixpkgs
            # ddgs instructor crawl4ai
          ];

          postPatch = ''
            sed -i pyproject.toml \
              -e '/ddgs>=9/d' \
              -e '/crawl4ai>=0/d' \
              -e '/instructor>=1/d' \
              -e '/mkdocs>=1/d' \
              -e '/mkdocs-material/d' \
              -e '/mkdocstrings>=0/d' \
              -e '/mkdocstrings-python/d' \
              -e '/textual>=8/d' \
              -e '/chromadb>=0/d' \
              -e '/nicegui>=3/d'

            # Rewrite absolute imports from src.* to standard package imports
            find src -name "*.py" -exec sed -i {} \
              -e 's/from src\.agentframework/from agentframework/g' \
              -e 's/import src\.agentframework/import agentframework/g' \
              -e 's/from src\.workflows/from workflows/g' \
              -e 's/import src\.workflows/import workflows/g' \;
          '';

          postInstall = ''
            cp -r src/workflows $out/${python.sitePackages}/
          '';
        };

        frontend = pkgs.buildNpmPackage {
          pname = "agentframework-frontend";
          version = "0.0.0";
          src = ./frontend;

          npmDepsHash = "sha256-x4KWVs8Fm8l6LANPr135X/AzucDFDsIxf9PUqI85n4k=";

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
              # Remove the redirect route and replace with static file serving
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

            # Load env from ~/.echo-ai/.env if it exists
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
              -e "s|__PYTHONPATH__|${python.pkgs.makePythonPath (agentframework.propagatedBuildInputs ++ [ agentframework ])}|g" \
              -e "s|__PYTHON__|${python.interpreter}|g" \
              -e "s|__SERVER_SCRIPT__|${server-script}|g"

            cp $out/libexec/serve-wrapper.sh $out/bin/agent-web
            chmod +x $out/bin/agent-web
          '';
        };

        devShell = pkgs.mkShell {
          packages = [
            python
            python.pkgs.pip
            python.pkgs.uv
            pkgs.nodejs_22
            pkgs.pre-commit
            pkgs.nixpkgs-fmt
            pkgs.gnumake
            pkgs.sqlite
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
            # Load env from ~/.echo-ai/.env if it exists
            if [ -f "$HOME/.echo-ai/.env" ]; then
                set -a
                source "$HOME/.echo-ai/.env"
                set +a
            fi

            echo "Syncing backend dependencies..."
            uv sync --extra dev --extra otel --extra ui --extra vector-db

            echo ""
            echo "Agent Framework dev environment ready"
            echo "  Backend:  uv sync --extra dev --extra otel --extra ui --extra vector-db (synced automatically on entry)"
            echo "  Frontend: cd frontend && npm install"
            echo "  Config:   ~/.echo-ai/config.yaml"
            echo "  Nix Ops:"
            echo "    Format code:      nix fmt"
            echo "    Build fullstack:  nix build"
            echo "    Run fullstack:    nix run ."
          '';
        };

      in
      {
        packages = {
          default = combined;
          backend = agentframework;
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
          backend = agentframework;
          frontend-pkg = frontend;
          fullstack = combined;
        };
      }
    );
}
