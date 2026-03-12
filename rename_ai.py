import glob

replacements = [
    ("Vibe AI", "Echo AI"),
    ("vibe-ai", "echo-ai"),
    ("VIBE_AI", "ECHO_AI")
]

targets = []
for ext in ["**/*.py", "**/*.md", "**/*.yaml", "**/*.yml", "**/*.sh"]:
    targets.extend(glob.glob(ext, recursive=True))

for filepath in set(targets):
    if ".venv" in filepath or "site/" in filepath or ".git" in filepath or "rename_ai.py" in filepath:
        continue
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    new_content = content
    for old, new in replacements:
        new_content = new_content.replace(old, new)
        
    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"Updated {filepath}")
