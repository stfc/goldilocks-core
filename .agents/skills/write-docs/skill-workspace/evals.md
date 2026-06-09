# Evals

## eval-1
Prompt: "Update the README after changing the staged pipeline API."

Expected behavior:
- Check code before writing.
- Document actual Python API.
- Do not invent a full staged CLI.
- Keep wording terse.

## eval-2
Prompt: "Add a Mermaid diagram to architecture docs."

Expected behavior:
- Draft a standalone `.mmd` file.
- Validate with the Mermaid skill tool.
- Embed only validated Mermaid.

## eval-3
Prompt: "Document a package restructure."

Expected behavior:
- Update module ownership.
- Remove references to deleted modules.
- Avoid compatibility-shim language unless explicitly requested.
