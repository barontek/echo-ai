//! Echo AI binary: CLI entry point and mode dispatcher.
//!
//! Mirrors `~/echo-ai-c/src/main.c`: parses flags, loads config, then
//! hands control to the web server (`--web`, the default) or the TUI
//! (`--cli`). The C version's `--chat` REPL is deliberately not ported,
//! and plugin loading is not part of this binary (plugins were cut from
//! the Rust port).
//!
//! Depends on: `echo-ai-core`, `echo-ai-server`, `echo-ai-tui` (wired in
//! as their phases land).

// TODO(multiple_crate_versions): hashbrown 0.14/0.17 (rusqlite vs toml
// indexmap) and syn 2/3 are unavoidable transitive pairs; `cargo deny`
// reports them at warn (deny.toml) and the review doc records the
// exception.
#![allow(clippy::multiple_crate_versions)]

use std::path::Path;
use std::process::ExitCode;

use echo_ai_core::Error;
use echo_ai_core::config::Config;
use echo_ai_core::utils::logging;

const USAGE: &str = "\
Usage: echo-ai [OPTIONS]

Options:
  --web            Run the HTTP(S) server (default)
  --cli            Run the terminal UI
  --config PATH    Path to config file (default: config.toml)
  --debug          Enable debug-level logging
  --help           Show this help message
";

/// Frontend mode selected on the command line.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Mode {
    Web,
    Cli,
}

/// Parsed command line.
#[derive(Debug)]
struct Parsed {
    mode: Mode,
    config_path: String,
    debug: bool,
}

/// Argument parsing failure: an unknown flag, or `--help` (which is
/// handled by printing usage, not by an error message).
#[derive(Debug)]
enum ArgError {
    Help,
    Unknown(String),
}

/// Parses CLI arguments. `--help` returns `Err(ArgError::Help)` so the
/// caller decides how to render it; every other failure carries the
/// offending argument in the error.
fn parse_args<I>(mut args: I) -> Result<Parsed, ArgError>
where
    I: Iterator<Item = String>,
{
    let mut mode = Mode::Web;
    let mut config_path = String::from("config.toml");
    let mut debug = false;

    // `while let` (not `for`) so `--config` can consume the following
    // element from the same iterator mid-loop.
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--web" => mode = Mode::Web,
            "--cli" => mode = Mode::Cli,
            "--debug" => debug = true,
            "--help" => return Err(ArgError::Help),
            "--config" => {
                // The value is the next argv element, not an attached
                // `--config=path`.
                config_path = args.next().ok_or_else(|| {
                    ArgError::Unknown(String::from("--config requires a PATH argument"))
                })?;
            }
            other => return Err(ArgError::Unknown(format!("unknown argument: {other}"))),
        }
    }

    Ok(Parsed {
        mode,
        config_path,
        debug,
    })
}

fn main() -> ExitCode {
    let parsed = match parse_args(std::env::args().skip(1)) {
        Ok(parsed) => parsed,
        Err(ArgError::Help) => {
            print!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        Err(ArgError::Unknown(msg)) => {
            eprintln!("echo-ai: {msg}");
            eprintln!("Try 'echo-ai --help' for usage.");
            return ExitCode::FAILURE;
        }
    };

    match run(parsed) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            eprintln!("echo-ai: {msg}");
            ExitCode::FAILURE
        }
    }
}

fn run(parsed: Parsed) -> Result<(), String> {
    let Parsed {
        mode,
        config_path,
        debug,
    } = parsed;

    if debug {
        logging::set_level(logging::Level::Debug);
    }

    let config = load_config(&config_path)?;

    match mode {
        Mode::Web => run_web(config),
        Mode::Cli => run_cli(config),
    }
}

fn run_web(config: Config) -> Result<(), String> {
    let rt = tokio::runtime::Runtime::new().map_err(|e| e.to_string())?;
    rt.block_on(echo_ai_server::run_server(config))
        .map_err(|e| e.to_string())
}

fn run_cli(config: Config) -> Result<(), String> {
    let rt = tokio::runtime::Runtime::new().map_err(|e| e.to_string())?;
    rt.block_on(echo_ai_tui::run_tui(config, None))
}

/// Loads config, failing fast on a missing *explicitly configured* file;
/// the default path loads clean defaults instead.
fn load_config(path: &str) -> Result<Config, String> {
    let config_path = Path::new(path);
    if config_path != Path::new("config.toml") && !config_path.exists() {
        return Err(format!("config file not found: {path}"));
    }
    Config::load(config_path).map_err(|e| match e {
        Error::Config(msg) => msg,
        Error::Io { path, source } => format!("{}: {source}", path.display()),
        other => other.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(args: &[&str]) -> Result<Parsed, ArgError> {
        parse_args(args.iter().map(|s| String::from(*s)))
    }

    #[test]
    fn defaults_to_web_mode_with_default_config_path() {
        let parsed = parse(&[]).expect("empty args parse");
        assert_eq!(parsed.mode, Mode::Web);
        assert_eq!(parsed.config_path, "config.toml");
        assert!(!parsed.debug);
    }

    #[test]
    fn cli_flag_selects_tui_mode() {
        let parsed = parse(&["--cli"]).expect("--cli parses");
        assert_eq!(parsed.mode, Mode::Cli);
    }

    #[test]
    fn config_flag_takes_next_argument_as_path() {
        let parsed = parse(&["--config", "/tmp/echo.toml"]).expect("--config parses");
        assert_eq!(parsed.config_path, "/tmp/echo.toml");
    }

    #[test]
    fn config_flag_without_argument_is_an_error() {
        let err = parse(&["--config"]).expect_err("missing value must fail");
        assert!(matches!(err, ArgError::Unknown(_)));
    }

    #[test]
    fn debug_flag_enables_debug_logging() {
        let parsed = parse(&["--debug"]).expect("--debug parses");
        assert!(parsed.debug);
    }

    #[test]
    fn unknown_flag_is_an_error() {
        let err = parse(&["--nope"]).expect_err("unknown flag must fail");
        assert!(matches!(err, ArgError::Unknown(msg) if msg.contains("--nope")));
    }

    #[test]
    fn help_flag_is_reported_but_is_not_an_error() {
        let err = parse(&["--help"]).expect_err("--help short-circuits parsing");
        assert!(matches!(err, ArgError::Help));
    }

    #[test]
    fn run_rejects_explicit_missing_config_path() {
        let parsed = parse(&["--config", "/nonexistent/echo-ai/config.toml"]).expect("args parse");
        let err = run(parsed).expect_err("missing explicit config must fail");
        assert!(
            err.contains("config file not found"),
            "unexpected error: {err}"
        );
    }

    #[test]
    fn cli_mode_reaches_tui_dispatch() {
        // The TUI run requires a terminal; the dispatch itself is what
        // we assert: parse of --cli selects Mode::Cli.
        let parsed = parse(&["--cli"]).expect("args parse");
        assert_eq!(parsed.mode, Mode::Cli);
    }
}
