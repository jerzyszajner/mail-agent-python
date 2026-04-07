import json
import sys

tool_args = json.load(sys.stdin)
read_path = (
    tool_args.get("tool_input", {}).get("file_path")
    or tool_args.get("tool_input", {}).get("path")
    or ""
)

blocked = [".env", "credentials.json", "token.json"]

if any(name in read_path for name in blocked):
    print(f"Blocked: reading {read_path} is not allowed", file=sys.stderr)
    sys.exit(2)
