#!/usr/bin/env python3
"""Measure representative API endpoint latency and response sizes."""

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

import httpx


DEMO_EMAIL = "admin@test.com"
DEMO_PASSWORD = "password123"
CACHE_STATES = ("HIT", "MISS", "BYPASS", "ausente")


@dataclass(frozen=True)
class Sample:
    elapsed_ms: float
    size_kb: float
    cache_state: str


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--label", required=True)
    parser.add_argument("--runs", type=positive_int, default=30)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.label) or args.label in {".", ".."}:
        parser.error("--label must contain only letters, numbers, dots, underscores or hyphens")
    return args


def request_sample(
    client: httpx.Client,
    path: str,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, Sample]:
    response = client.get(path, headers=headers)
    response.raise_for_status()
    timing_header = response.headers.get("X-Response-Time-ms")
    if timing_header is None:
        raise RuntimeError(
            f"{path} response is missing the X-Response-Time-ms timing header"
        )
    try:
        elapsed_ms = float(timing_header)
    except ValueError as exc:
        raise RuntimeError(
            f"{path} returned an invalid X-Response-Time-ms value"
        ) from exc

    cache_value = response.headers.get("X-Cache")
    cache_state = cache_value.strip().upper() if cache_value else "ausente"
    return response, Sample(
        elapsed_ms=elapsed_ms,
        size_kb=len(response.content) / 1024,
        cache_state=cache_state,
    )


def measure_endpoint(
    client: httpx.Client,
    path: str,
    runs: int,
    headers: dict[str, str] | None = None,
) -> tuple[httpx.Response, Sample, list[Sample]]:
    cold_response, cold_sample = request_sample(client, path, headers)
    warm_samples = [
        request_sample(client, path, headers)[1]
        for _ in range(runs)
    ]
    return cold_response, cold_sample, warm_samples


def require_list(response: httpx.Response, path: str) -> list[Any]:
    value = response.json()
    if not isinstance(value, list):
        raise RuntimeError(f"{path} did not return a JSON array")
    return value


def percentile(values: list[float], percentile_value: int) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value / 100 * len(ordered)))
    return ordered[rank - 1]


def cache_counts(samples: list[Sample]) -> str:
    counts = Counter(sample.cache_state for sample in samples)
    parts = [f"{state}={counts[state]}" for state in CACHE_STATES]
    parts.extend(
        f"{state}={count}"
        for state, count in sorted(counts.items())
        if state not in CACHE_STATES
    )
    return ", ".join(parts)


def format_endpoint_row(
    path: str,
    cold: Sample,
    samples: list[Sample],
) -> str:
    timings = [sample.elapsed_ms for sample in samples]
    average_size_kb = sum(sample.size_kb for sample in samples) / len(samples)
    return (
        f"| `{path}` | {cold.elapsed_ms:.1f} ms / {cold.size_kb:.2f} KB "
        f"({cold.cache_state}) | {min(timings):.1f} | "
        f"{percentile(timings, 50):.1f} | {percentile(timings, 95):.1f} | "
        f"{max(timings):.1f} | {average_size_kb:.2f} | "
        f"{cache_counts(samples)} |"
    )


def login(client: httpx.Client) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("/auth/login response did not contain an access token")
    return {"Authorization": f"Bearer {token}"}


def run_benchmark(args: argparse.Namespace) -> str:
    rows: list[str] = []
    volumes: dict[str, int] = {}

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0) as client:
        products_response, cold, samples = measure_endpoint(
            client, "/inventory/products", args.runs
        )
        products = require_list(products_response, "/inventory/products")
        volumes["Productos"] = len(products)
        if not products or not isinstance(products[0], dict) or "id" not in products[0]:
            raise RuntimeError(
                "/inventory/products must return at least one product with an id"
            )
        product_path = f"/inventory/products/{quote(str(products[0]['id']), safe='')}"
        rows.append(format_endpoint_row("/inventory/products", cold, samples))

        orders_response, cold, samples = measure_endpoint(
            client, "/inventory/orders", args.runs
        )
        volumes["Órdenes"] = len(require_list(orders_response, "/inventory/orders"))
        rows.append(format_endpoint_row("/inventory/orders", cold, samples))

        _, cold, samples = measure_endpoint(client, product_path, args.runs)
        rows.append(format_endpoint_row(product_path, cold, samples))

        incidents_response, cold, samples = measure_endpoint(
            client, "/api/incidents", args.runs
        )
        require_list(incidents_response, "/api/incidents")
        rows.append(format_endpoint_row("/api/incidents", cold, samples))

        summary_response, cold, samples = measure_endpoint(
            client, "/api/incidents/summary", args.runs
        )
        summary = summary_response.json()
        if not isinstance(summary, dict) or not isinstance(summary.get("total"), int):
            raise RuntimeError(
                "/api/incidents/summary must return a JSON object with integer total"
            )
        volumes["Incidencias"] = summary["total"]
        rows.append(format_endpoint_row("/api/incidents/summary", cold, samples))

        auth_headers = login(client)
        _, cold, samples = measure_endpoint(
            client, "/suppliers", args.runs, auth_headers
        )
        rows.append(format_endpoint_row("/suppliers", cold, samples))

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    volume_table = "\n".join(
        f"| {name} | {count} |" for name, count in volumes.items()
    )
    table = "\n".join(rows)
    return f"""# Endpoint benchmark — {args.label}

- Fecha/hora UTC: {timestamp}
- Base URL: `{args.base_url}`
- Repeticiones tras la primera petición fría: {args.runs}
- Latencia: cabecera `X-Response-Time-ms` emitida por la API.

## Volumen de datos

| Tipo | Registros |
|---|---:|
{volume_table}

## Resultados

La columna fría informa latencia, tamaño y `X-Cache` de la primera petición.
Las estadísticas min/p50/p95/max, tamaño KB medio y contadores `X-Cache`
corresponden a las {args.runs} peticiones siguientes.

| Endpoint | Primera (fría) | Min ms | p50 ms | p95 ms | Max ms | Media KB | X-Cache (repeticiones) |
|---|---:|---:|---:|---:|---:|---:|---|
{table}
"""


def main() -> None:
    args = parse_args()
    report = run_benchmark(args)
    output_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "caching"
        / "benchmarks"
        / f"{args.label}.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"\nBenchmark guardado en {output_path}")


if __name__ == "__main__":
    main()
