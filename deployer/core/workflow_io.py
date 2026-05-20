"""Load a ComfyUI workflow graph from a ``.json`` file or a generated image.

ComfyUI embeds the workflow in the images it saves:

* **PNG** — as text chunks (``info["workflow"]`` for the UI graph,
  ``info["prompt"]`` for the API prompt).
* **WebP / JPEG** — in EXIF: the UI graph under ``ImageDescription`` and the
  API prompt under ``Make``, each prefixed with ``Workflow:`` / ``Prompt:``.
  Some custom nodes also stuff JSON into ``UserComment``.

This module returns everything in the **UI workflow shape** — a dict with a
``nodes`` list whose entries carry ``type`` and ``widgets_values`` — so the
existing node-type / model-ref parsers work unchanged. When only the API
``prompt`` format is available it is converted to a minimal pseudo-graph.
"""

import json
import os


_WORKFLOW_IMAGE_EXTENSIONS = {".png", ".webp", ".jpg", ".jpeg"}

# EXIF tag IDs ComfyUI writes to (and a UserComment fallback for custom nodes).
_EXIF_IMAGE_DESCRIPTION = 0x010E  # UI graph, prefixed "Workflow:"
_EXIF_MAKE = 0x010F               # API prompt, prefixed "Prompt:"
_EXIF_USER_COMMENT = 0x9286
_EXIF_TAGS = (_EXIF_IMAGE_DESCRIPTION, _EXIF_MAKE, _EXIF_USER_COMMENT)

_METADATA_PREFIXES = ("Workflow:", "Prompt:", "workflow:", "prompt:")


def is_supported_workflow_file(path: str) -> bool:
    """True if *path* is a workflow source we know how to read."""
    ext = os.path.splitext(path)[1].lower()
    return ext == ".json" or ext in _WORKFLOW_IMAGE_EXTENSIONS


def load_workflow_graph(path: str) -> dict:
    """Return a UI-workflow dict (with a ``nodes`` list) from *path*.

    *path* may be a raw ``.json`` workflow export or a ComfyUI-generated
    image with the workflow embedded in its metadata.

    Raises ``ValueError`` if an image carries no recognisable workflow.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    graph = _extract_workflow_from_image(path)
    if graph is None:
        raise ValueError(
            f"No embedded ComfyUI workflow found in {os.path.basename(path)}"
        )
    return graph


# ---------------------------------------------------------------------------
# Image metadata extraction
# ---------------------------------------------------------------------------

def _extract_workflow_from_image(path: str) -> dict | None:
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is not installed; cannot read workflows embedded in images.")
        return None

    try:
        with Image.open(path) as img:
            info = dict(img.info)
            try:
                exif = dict(img.getexif())
            except Exception:
                exif = {}
    except Exception as exc:
        print(f"Could not open image {os.path.basename(path)}: {exc}")
        return None

    # 1. PNG text chunks — prefer the UI graph, then the API prompt.
    graph = _graph_from_field(info.get("workflow"))
    if graph is not None:
        return graph

    # 2. EXIF (WebP / JPEG), including a UserComment fallback.
    for tag in _EXIF_TAGS:
        graph = _graph_from_field(exif.get(tag))
        if graph is not None:
            return graph

    # 3. API prompt fallback (PNG "prompt" chunk).
    graph = _graph_from_field(info.get("prompt"))
    if graph is not None:
        return graph

    return None


def _graph_from_field(value) -> dict | None:
    """Parse a metadata field into a UI graph, handling EXIF prefixes and API format."""
    data = _parse_json_field(value)
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("nodes"), list):
        return data            # already a UI workflow graph
    return _graph_from_prompt(data)  # looks like an API prompt → synthesise


def _parse_json_field(value) -> object | None:
    """Decode a metadata value (bytes/str, optionally EXIF-prefixed) into JSON."""
    if value is None:
        return None
    if isinstance(value, bytes):
        # EXIF UserComment is often prefixed with an 8-byte charset code.
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("\x00").strip()
    for prefix in _METADATA_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    if not text:
        return None
    # Trim a leading non-JSON charset marker like "ASCII\x00\x00\x00".
    brace = text.find("{")
    if brace > 0:
        text = text[brace:]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _graph_from_prompt(prompt: dict) -> dict | None:
    """Convert an API ``prompt`` dict into a minimal UI-graph pseudo-shape.

    API format is ``{node_id: {"class_type": str, "inputs": {...}}}``. The
    node type comes from ``class_type``; literal (non-link) input values are
    collected as ``widgets_values`` so the model-reference heuristic still
    has something to scan.
    """
    nodes = []
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type:
            continue
        widgets = [
            v for v in node.get("inputs", {}).values()
            if isinstance(v, (str, int, float, bool))
        ]
        nodes.append({"type": class_type, "widgets_values": widgets})
    if not nodes:
        return None
    return {"nodes": nodes}
