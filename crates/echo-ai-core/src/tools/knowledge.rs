//! `Knowledge` tools: `notes` (personal markdown notes), `memory`
//! (persistent user facts via the session store), `sqlite_query` and
//! `sqlite_schema` (read-only inspection of the session database).
//!
//! Depends on: crate `session`, `tools::tool`.

use futures_util::future::BoxFuture;
use serde_json::{Value, json};
use std::path::Path;

use super::tool::{Tool, ToolContext, ToolError, ToolOutput, arg_optional_string, arg_string};

/// Notes directory under the user config dir.
fn notes_dir() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
    Path::new(&home).join(".config/echo-ai/notes")
}

/// Validates a note name: alphanumeric, dash, underscore; `.md` implied.
fn validate_name(name: &str) -> Result<String, ToolError> {
    if name.is_empty()
        || name.len() > 64
        || !name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err(ToolError::InvalidArgs(format!(
            "invalid note name {name:?} (alphanumeric, dash, underscore only)"
        )));
    }
    Ok(String::from(name))
}

/// `notes`: list/read/write/delete personal markdown notes.
pub struct Notes;

impl Tool for Notes {
    fn name(&self) -> &'static str {
        "notes"
    }

    fn description(&self) -> &'static str {
        "Manage personal markdown notes: list, read, write, delete. Names are [a-z0-9_-]."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "read", "write", "delete"]},
                "name": {"type": "string"},
                "content": {"type": "string", "description": "For write"}
            },
            "required": ["action", "name"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        _ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let action = arg_string(&args, "action")?;
            let name = validate_name(&arg_string(&args, "name")?)?;
            let dir = notes_dir();
            std::fs::create_dir_all(&dir).map_err(|e| ToolError::Io {
                path: dir.clone(),
                source: e,
            })?;
            let path = dir.join(format!("{name}.md"));
            match action.as_str() {
                "list" => {
                    let mut names: Vec<String> = std::fs::read_dir(&dir)
                        .map_err(|e| ToolError::Io {
                            path: dir.clone(),
                            source: e,
                        })?
                        .filter_map(Result::ok)
                        .filter(|e| e.path().extension().is_some_and(|x| x == "md"))
                        .map(|e| e.file_name().to_string_lossy().replace(".md", ""))
                        .collect();
                    names.sort();
                    Ok(ToolOutput::text(if names.is_empty() {
                        String::from("(no notes)")
                    } else {
                        names.join("\n")
                    }))
                }
                "read" => {
                    let content = std::fs::read_to_string(&path).map_err(|e| ToolError::Io {
                        path: path.clone(),
                        source: e,
                    })?;
                    Ok(ToolOutput::text(content))
                }
                "write" => {
                    let content = arg_string(&args, "content")?;
                    std::fs::write(&path, content.as_bytes()).map_err(|e| ToolError::Io {
                        path: path.clone(),
                        source: e,
                    })?;
                    Ok(ToolOutput::text(format!("note {name} written")))
                }
                "delete" => {
                    std::fs::remove_file(&path).map_err(|e| ToolError::Io {
                        path: path.clone(),
                        source: e,
                    })?;
                    Ok(ToolOutput::text(format!("note {name} deleted")))
                }
                other => Err(ToolError::InvalidArgs(format!("unknown action {other}"))),
            }
        })
    }
}

/// `memory`: persistent user facts (get/set/delete/list).
pub struct Memory;

impl Tool for Memory {
    fn name(&self) -> &'static str {
        "memory"
    }

    fn description(&self) -> &'static str {
        "Persistent user memory: get, set, delete, or list facts the user wants remembered across sessions."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "set", "delete", "list"]},
                "key": {"type": "string"},
                "value": {"type": "string", "description": "For set"}
            },
            "required": ["action"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let Some(session) = ctx.session else {
                return Err(ToolError::Execution(String::from(
                    "session persistence is disabled; memory unavailable",
                )));
            };
            let action = arg_string(&args, "action")?;
            let key = arg_optional_string(&args, "key").unwrap_or_default();
            match action.as_str() {
                "get" => {
                    let value = session
                        .memory_get(&key)
                        .map_err(|e| ToolError::Execution(e.to_string()))?;
                    Ok(match value {
                        Some(v) => ToolOutput::text(v),
                        None => ToolOutput::text(format!("(no memory for {key})")),
                    })
                }
                "set" => {
                    let value = arg_string(&args, "value")?;
                    session
                        .memory_set(&key, &value)
                        .map_err(|e| ToolError::Execution(e.to_string()))?;
                    Ok(ToolOutput::text(format!("memory {key} saved")))
                }
                "delete" => {
                    session
                        .memory_delete(&key)
                        .map_err(|e| ToolError::Execution(e.to_string()))?;
                    Ok(ToolOutput::text(format!("memory {key} deleted")))
                }
                "list" => {
                    let facts = session
                        .memory_list()
                        .map_err(|e| ToolError::Execution(e.to_string()))?;
                    if facts.is_empty() {
                        return Ok(ToolOutput::text("(no memory facts)"));
                    }
                    let text = facts
                        .iter()
                        .map(|(k, v)| format!("{k}: {v}"))
                        .collect::<Vec<_>>()
                        .join("\n");
                    Ok(ToolOutput::text(text))
                }
                other => Err(ToolError::InvalidArgs(format!("unknown action {other}"))),
            }
        })
    }
}

/// `sqlite_query`: read-only `SELECT`/`PRAGMA`/`EXPLAIN` on the session
/// database.
pub struct SqliteQuery;

impl Tool for SqliteQuery {
    fn name(&self) -> &'static str {
        "sqlite_query"
    }

    fn description(&self) -> &'static str {
        "Run a read-only query (SELECT/PRAGMA/EXPLAIN) against the session database. Returns JSON rows."
    }

    fn parameters(&self) -> Value {
        json!({
            "type": "object",
            "properties": {
                "sql": {"type": "string"}
            },
            "required": ["sql"]
        })
    }

    fn execute<'a>(
        &self,
        args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let sql = arg_string(&args, "sql")?;
            let trimmed = sql.trim_start().to_ascii_uppercase();
            if !["SELECT", "PRAGMA", "EXPLAIN", "WITH"]
                .iter()
                .any(|p| trimmed.starts_with(p))
            {
                return Err(ToolError::InvalidArgs(String::from(
                    "only SELECT/PRAGMA/EXPLAIN/WITH queries are allowed",
                )));
            }
            let Some(session) = ctx.session else {
                return Err(ToolError::Execution(String::from(
                    "session persistence is disabled",
                )));
            };
            let rows = session
                .query_read_only(&sql)
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let pretty = serde_json::to_string_pretty(&rows).unwrap_or_else(|_| String::from("[]"));
            Ok(ToolOutput::structured(pretty.clone(), rows))
        })
    }
}

/// `sqlite_schema`: table list with `CREATE` SQL and column info.
pub struct SqliteSchema;

impl Tool for SqliteSchema {
    fn name(&self) -> &'static str {
        "sqlite_schema"
    }

    fn description(&self) -> &'static str {
        "Describe the session database schema (tables, CREATE SQL, columns)."
    }

    fn parameters(&self) -> Value {
        json!({"type": "object", "properties": {}})
    }

    fn execute<'a>(
        &self,
        _args: Value,
        ctx: &'a ToolContext<'a>,
    ) -> BoxFuture<'a, std::result::Result<ToolOutput, ToolError>> {
        Box::pin(async move {
            let Some(session) = ctx.session else {
                return Err(ToolError::Execution(String::from(
                    "session persistence is disabled",
                )));
            };
            let schema = session
                .schema_info()
                .map_err(|e| ToolError::Execution(e.to_string()))?;
            let pretty =
                serde_json::to_string_pretty(&schema).unwrap_or_else(|_| String::from("{}"));
            Ok(ToolOutput::structured(pretty.clone(), schema))
        })
    }
}
