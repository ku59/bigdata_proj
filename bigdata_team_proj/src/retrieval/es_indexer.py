import json
import requests
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "elasticsearch.yaml"

def load_es_config(config_path: Path = CONFIG_PATH):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

_cfg = load_es_config()
ES_URL = _cfg["es_url"]
ES_INDEX = _cfg["index_name"]
ES_USER = _cfg["username"]
ES_PASS = _cfg["password"]

def bulk_index_news(docs_es):
    """
    ES(news_index)에 bulk 적재.
    docs_es: [{ "id": str, "body": dict }, ...]
    """
    if not docs_es:
        print("ES에 적재할 데이터가 없습니다.")
        return

    lines = []
    for d in docs_es:
        header = {"index": {"_index": ES_INDEX, "_id": d["id"]}}
        lines.append(json.dumps(header))
        lines.append(json.dumps(d["body"], ensure_ascii=False))

    bulk_body = "\n".join(lines) + "\n"

    response = requests.post(
        ES_URL,
        data=bulk_body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        auth=(ES_USER, ES_PASS),
    )

    print("\n[ES 적재 결과]")
    print("status:", response.status_code)
    print(response.text[:500])
