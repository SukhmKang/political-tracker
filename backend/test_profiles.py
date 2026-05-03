"""
Quick smoke-test: fetch profiles for a handful of known entities.
Run with: python test_profiles.py  (server must be running on localhost:8000)
"""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://localhost:8000"

# Top entities by mention_count from unified.entities
TEST_IDS = [
    (1128322, "ActBlue Virginia"),
    (766333,  "Youngkin for Governor, Inc."),
    (852937,  "Texans for Greg Abbott"),
    (28562,   "Texas Association of Realtors PAC"),
]


def fetch(entity_id: int):
    url = f"{BASE}/entities/{entity_id}/profile"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "reason": e.reason}
    except Exception as e:
        return {"error": str(e)}


def main():
    ok = True
    for entity_id, label in TEST_IDS:
        print(f"\n{'='*60}")
        print(f"Entity {entity_id}: {label}")
        print("=" * 60)
        data = fetch(entity_id)
        if "error" in data:
            print(f"  FAILED: {data}")
            ok = False
            continue

        e = data["entity"]
        f = data["finance"]
        h = data["expansion_hints"]

        print(f"  name         : {e['name']}")
        print(f"  type         : {e['type']}")
        print(f"  state        : {e['state']}")
        print(f"  mention_count: {e['mention_count']}")
        print(f"  incoming     : ${f['incoming_total']:>15,.0f}  ({f['incoming_count']} edges, {f['unique_sources']} sources)")
        print(f"  outgoing     : ${f['outgoing_total']:>15,.0f}  ({f['outgoing_count']} edges, {f['unique_targets']} targets)")
        print(f"  top_source[0]: {f['top_sources'][0]['name'] if f['top_sources'] else 'n/a'}")
        print(f"  top_target[0]: {f['top_targets'][0]['name'] if f['top_targets'] else 'n/a'}")
        print(f"  recent edges : {len(f['recent_edges'])}")
        print(f"  high_degree  : {h['is_high_degree']}")
        print(f"  high_dollar  : {h['is_high_dollar']}")
        print(f"  opaque_name  : {h['is_opaque_name']}")
        print(f"  inv_type     : {h['suggested_investigation_type']}")
        print(f"  reasons      : {h['reasons']}")

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
