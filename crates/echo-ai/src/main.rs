//! Echo AI binary: CLI entry point and mode dispatcher.
//!
//! Mirrors `~/echo-ai-c/src/main.c`: parses flags, then hands control to
//! the web server (`--web`, the default) or the TUI (`--cli`). The C
//! version's `--chat` REPL is deliberately not ported, and plugin loading
//! is not part of this binary (plugins were cut from the Rust port).
//!
//! Depends on: `echo-ai-core`, `echo-ai-server`, `echo-ai-tui` (wired in
//! as their phases land).

use std::process::ExitCode;

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
        // Full debug-level logging setup lands with Phase 1 (config).
        eprintln!("echo-ai: debug logging enabled");
    }

    // Phase 1 wires real config loading; until then, fail fast when an
    // explicitly configured file is missing so a typo'd --config path is
    // caught immediately rather than surfacing as a confusing mode error.
    if config_path != "config.toml" && !std::path::Path::new(&config_path).exists() {
        return Err(format!("config file not found: {config_path}"));
    }

    match mode {
        Mode::Web => Err(String::from(
            "web mode is not ported yet (planned for Phase 5)",
        )),
        Mode::Cli => Err(String::from(
            "cli mode is not ported yet (planned for Phase 6)",
        )),
    }
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
    fn run_defaults_config_path_to_implicit_and_reaches_mode_dispatch() {
        let parsed = parse(&[]).expect("args parse");
        let err = run(parsed).expect_err("unported mode must fail");
        assert!(err.contains("Phase 5"), "unexpected error: {err}");
    }
}
