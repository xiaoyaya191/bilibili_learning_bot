"""Conflict-aware persistence for independent UI and worker snapshots."""
from copy import deepcopy
import unicodedata


def canonical_keyword(value):
    return unicodedata.normalize('NFKC', str(value)).strip().casefold()


def merge_delta(base, edited, live):
    result = deepcopy(live)
    for key in base.keys() | edited.keys():
        if key == 'updated_at' or base.get(key) == edited.get(key):
            continue
        if key not in edited:
            result.pop(key, None)
        elif key == 'interests':
            previous = {canonical_keyword(item['keyword']): item for item in base.get(key, [])}
            desired = {canonical_keyword(item['keyword']): item for item in edited[key]}
            current = {canonical_keyword(item['keyword']): item for item in live.get(key, [])}
            def same_item(left, right):
                if left is None or right is None:
                    return left is right
                left = deepcopy(left)
                right = deepcopy(right)
                left['keyword'] = canonical_keyword(left.get('keyword', ''))
                right['keyword'] = canonical_keyword(right.get('keyword', ''))
                return left == right
            for keyword in previous.keys() - desired.keys():
                if same_item(current.get(keyword), previous[keyword]):
                    current.pop(keyword, None)
            for keyword, item in desired.items():
                if same_item(previous.get(keyword), item):
                    continue
                present = current.get(keyword)
                if item.get('source') != 'manual':
                    if present is not None and present.get('source') == 'manual':
                        continue
                    if keyword not in previous and present is not None:
                        continue
                    if keyword in previous and not same_item(present, previous[keyword]):
                        continue
                if keyword in previous and present is None:
                    continue
                current[keyword] = deepcopy(item)
            result[key] = list(current.values())
        elif key == 'videos_watched_count':
            result[key] = max(0, live.get(key, 0) + edited[key] - base.get(key, 0))
        elif key == 'history_tags':
            additions = [tag for tag in edited[key] if tag not in base.get(key, [])]
            result[key] = list(dict.fromkeys(live.get(key, []) + additions))[-500:]
        elif isinstance(edited[key], dict) and isinstance(base.get(key), dict):
            result[key] = merge_delta(base[key], edited[key], live.get(key, {}))
        else:
            result[key] = deepcopy(edited[key])
    return result
