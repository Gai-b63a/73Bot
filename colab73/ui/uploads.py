"""Normalize and release file uploads in ipywidgets 7 and 8."""


def uploaded_file(value):
    if not value:
        return None
    if isinstance(value, dict):
        key, item = next(iter(value.items()))
        name = item.get("name") or item.get("metadata", {}).get("name") or key
    else:
        item = value[0]
        name = item["name"]
    return {"name": name, "content": item["content"]}


def release_upload(widget):
    # Colab can already have widgets 7 loaded before the preparation cell
    # installs widgets 8. In 7, value is a read-only view of metadata and data.
    with widget.hold_trait_notifications():
        if widget.traits()["value"].read_only:
            widget.data = []
            widget.metadata = []
            widget.set_trait("value", {})
        else:
            widget.value = ()
        if "_counter" in widget.traits():
            widget._counter = 0
