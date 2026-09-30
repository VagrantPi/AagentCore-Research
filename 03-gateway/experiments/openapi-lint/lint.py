"""把 OpenAPI 規格接成 Gateway 工具之前的檢查。

檢查項目依據 AgentCore Gateway 的 OpenAPI 限制（2026-09 文件）：
  - 必須是 OpenAPI 3.x（不支援 Swagger 2.0）
  - 每個要曝露的 operation 都要有 operationId（它就是工具名稱）
  - 不支援 oneOf / anyOf / allOf
  - securitySchemes 會被忽略，驗證要在 Gateway 的 outbound 設定
  - 只有 application/json 完整支援
  - 伺服器 URL 不要用 host 變數
另外加上兩個經驗檢查（非官方限制）：
  - 完整工具名稱 <target>___<operationId> 超過 64 字元或含特殊字元時警告（許多模型的工具名稱上限）
  - 工具說明或參數說明缺漏時警告；估算 tools/list 的大小

用法：python lint.py spec.json --target OrderApi
"""
import argparse
import json
import re
import sys

METHODS = {"get", "put", "post", "delete", "patch", "head", "options"}
NAME_OK = re.compile(r"^[A-Za-z0-9_-]+$")


def load(path):
    text = open(path, encoding="utf-8").read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # 需要 pip install pyyaml
        return yaml.safe_load(text)
    return json.loads(text)


def walk(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path, k, v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def lint(spec, target):
    errors, warnings = [], []
    ver = str(spec.get("openapi", spec.get("swagger", "")))
    if not ver.startswith("3."):
        errors.append(f"版本 {ver or '未知'}：只支援 OpenAPI 3.x")
    if spec.get("components", {}).get("securitySchemes"):
        warnings.append("securitySchemes 會被忽略：驗證要改在 Gateway 的 outbound 設定")
    for s in spec.get("servers", []):
        if re.search(r"\{[^}]+\}", s.get("url", "")) and not all("enum" in v for v in s.get("variables", {}).values()):
            warnings.append(f"server URL 有變數但沒有 enum：{s['url']}")
    for p, k, _ in walk(spec):
        if k in ("oneOf", "anyOf", "allOf"):
            errors.append(f"不支援 {k}：{p}")

    tools = []
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method not in METHODS:
                continue
            where = f"{method.upper()} {path}"
            op_id = op.get("operationId")
            if not op_id:
                errors.append(f"{where}：缺少 operationId，不會變成工具")
                continue
            full = f"{target}___{op_id}"
            if len(full) > 64 or not NAME_OK.match(full):
                warnings.append(f"{where}：工具名稱 {full}（{len(full)} 字元）可能超出模型的工具名稱限制")
            desc = op.get("description") or op.get("summary")
            if not desc:
                warnings.append(f"{where}：沒有 description / summary，模型只能靠名稱猜用途")
            for prm in op.get("parameters", []):
                if not prm.get("description"):
                    warnings.append(f"{where}：參數 {prm.get('name')} 沒有說明")
            body = op.get("requestBody", {}).get("content", {})
            others = [ct for ct in body if ct != "application/json"]
            if others:
                warnings.append(f"{where}：request content type {others} 未完整支援")
            tools.append({"name": full, "description": desc or "", "op": op})

    size = len(json.dumps([{"name": t["name"], "description": t["description"],
                            "inputSchema": {"parameters": t["op"].get("parameters", []),
                                            "body": t["op"].get("requestBody", {})}} for t in tools], ensure_ascii=False))
    return tools, errors, warnings, size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--target", required=True, help="Gateway target 名稱（會成為工具名稱的前綴）")
    a = ap.parse_args()
    tools, errors, warnings, size = lint(load(a.spec), a.target)
    print(f"工具數：{len(tools)}；tools/list 約 {size:,} 字元（以 4 字元 ≈ 1 token 粗估約 {size // 4:,} token；中文比例更高。每一輪對話都會送進模型）")
    for e in errors:
        print("ERROR  ", e)
    for w in warnings:
        print("WARN   ", w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
