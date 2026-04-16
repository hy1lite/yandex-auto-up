def _parse_selection(selection: str, max_index: int) -> list[int]:
    """Parse user selection like '1,2,3' or 'all' into list of indices."""
    selection = selection.strip().lower()
    if selection == "all":
        return list(range(1, max_index + 1))
    
    try:
        indices = [int(chunk.strip()) for chunk in selection.split(",") if chunk.strip()]
        return [idx for idx in indices if 1 <= idx <= max_index]
    except ValueError:
        return []
