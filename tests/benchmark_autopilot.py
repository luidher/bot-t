#!/usr/bin/env python3
"""
Benchmark de simulación para comparar dos estrategias de respuesta:
  - `db_first`: usar DB si existe, si no elegir aleatorio.
  - `random_first`: ignorar DB al elegir (responder aleatoriamente), pero
    aprender (guardar) respuestas correctas tras feedback.

El script simula hojas con N preguntas y mide tiempo y tasa de errores.

Ejemplo:
  python tests/benchmark_autopilot.py --runs 200
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
from typing import Dict, List, Tuple


def generate_questions(n_questions: int, options_per_q: int, rng: random.Random):
    questions = {}
    for i in range(n_questions):
        qid = f"q{i}"
        k = options_per_q
        correct = rng.randrange(k)
        questions[qid] = {
            "options": list(range(k)),
            "correct": correct,
        }
    return questions


class SimpleDB:
    def __init__(self):
        self.store: Dict[str, int] = {}

    def prepopulate(self, questions: Dict[str, dict], fraction: float, correct_frac: float, rng: random.Random):
        qids = list(questions.keys())
        k = max(1, int(round(len(qids) * fraction)))
        chosen = rng.sample(qids, k) if k <= len(qids) else qids
        for q in chosen:
            if rng.random() < correct_frac:
                self.store[q] = questions[q]["correct"]
            else:
                opts = questions[q]["options"]
                wrongs = [o for o in opts if o != questions[q]["correct"]]
                self.store[q] = rng.choice(wrongs) if wrongs else questions[q]["correct"]

    def get(self, qid: str):
        return self.store.get(qid)

    def save(self, qid: str, option: int):
        self.store[qid] = option

    def contains(self, qid: str) -> bool:
        return qid in self.store


def simulate_sheet(
    questions: Dict[str, dict],
    strategy: str,
    db: SimpleDB,
    max_rounds: int = 8,
    timings: dict | None = None,
    rng: random.Random | None = None,
) -> dict:
    if rng is None:
        rng = random.Random()
    if timings is None:
        timings = {
            "db_lookup_ms": 2.0,
            "random_pick_ms": 0.5,
            "select_ms": 0.5,
            "submit_ms": 120.0,
            "feedback_proc_ms": 2.0,
            "reload_ms": 80.0,
        }

    unsolved = set(questions.keys())
    discarded: Dict[str, set] = {qid: set() for qid in questions}
    attempts: Dict[str, int] = {qid: 0 for qid in questions}
    first_try_success = 0
    rounds = 0
    time_ms = 0.0
    db_hits = 0
    db_writes = 0

    while unsolved and rounds < max_rounds:
        rounds += 1
        selections: Dict[str, int] = {}

        # Selección de opciones para esta ronda
        for q in list(unsolved):
            opts = [o for o in questions[q]["options"] if o not in discarded[q]]
            if not opts:
                # agotadas todas las opciones
                selections[q] = None
                continue

            if strategy == "db_first":
                val = db.get(q)
                if val is not None and val not in discarded[q]:
                    sel = val
                    db_hits += 1
                    time_ms += timings["db_lookup_ms"]
                else:
                    sel = rng.choice(opts)
                    time_ms += timings["random_pick_ms"]
            elif strategy == "random_first":
                # ignorar DB a la hora de elegir
                sel = rng.choice(opts)
                time_ms += timings["random_pick_ms"]
            else:
                raise ValueError("strategy must be 'db_first' or 'random_first'")

            selections[q] = sel
            attempts[q] += 1

        # Envío de la hoja (un submit por ronda)
        time_ms += timings["submit_ms"]

        # Procesar feedback
        solved_this_round = []
        for q, sel in selections.items():
            if sel is None:
                # no quedan opciones
                continue
            correct = questions[q]["correct"]
            time_ms += timings["feedback_proc_ms"]
            if sel == correct:
                solved_this_round.append(q)
                # guardar en DB si no coincide
                prev = db.get(q)
                if prev != sel:
                    db.save(q, sel)
                    db_writes += 1
                if attempts[q] == 1:
                    first_try_success += 1
            else:
                discarded[q].add(sel)

        for q in solved_this_round:
            if q in unsolved:
                unsolved.remove(q)

        # Si quedan por resolver, simular recarga / intento de nuevo
        if unsolved and rounds < max_rounds:
            time_ms += timings["reload_ms"]

    # resultados
    total_q = len(questions)
    solved = total_q - len(unsolved)
    attempts_list = list(attempts.values())
    mean_attempts = statistics.mean(attempts_list) if attempts_list else 0
    median_attempts = statistics.median(attempts_list) if attempts_list else 0

    return {
        "strategy": strategy,
        "total_q": total_q,
        "solved": solved,
        "unsolved": len(unsolved),
        "rounds": rounds,
        "time_ms": time_ms,
        "db_hits": db_hits,
        "db_writes": db_writes,
        "mean_attempts": mean_attempts,
        "median_attempts": median_attempts,
        "first_try_success": first_try_success,
    }


def aggregate_runs(results: List[dict]) -> dict:
    N = len(results)
    ag = {}
    ag["runs"] = N
    ag["avg_time_ms"] = statistics.mean(r["time_ms"] for r in results)
    ag["avg_rounds"] = statistics.mean(r["rounds"] for r in results)
    ag["avg_solved"] = statistics.mean(r["solved"] for r in results)
    ag["avg_unsolved"] = statistics.mean(r["unsolved"] for r in results)
    ag["avg_db_hits"] = statistics.mean(r["db_hits"] for r in results)
    ag["avg_db_writes"] = statistics.mean(r["db_writes"] for r in results)
    ag["avg_mean_attempts"] = statistics.mean(r["mean_attempts"] for r in results)
    ag["avg_first_try_success"] = statistics.mean(r["first_try_success"] for r in results)
    return ag


def run_benchmark(
    runs: int = 200,
    n_questions: int = 100,
    options_per_q: int = 4,
    initial_db_frac: float = 0.0,
    db_correct_frac: float = 1.0,
    max_rounds: int = 8,
    seed: int | None = None,
):
    rng = random.Random(seed)
    results_db_first = []
    results_random_first = []

    for i in range(runs):
        # generar preguntas
        qs = generate_questions(n_questions, options_per_q, rng)

        # DB inicial
        db1 = SimpleDB()
        db1.prepopulate(qs, initial_db_frac, db_correct_frac, rng)

        db2 = SimpleDB()
        db2.prepopulate(qs, initial_db_frac, db_correct_frac, rng)

        r1 = simulate_sheet(qs, "db_first", db1, max_rounds=max_rounds, rng=random.Random(rng.randint(0, 2**30)))
        r2 = simulate_sheet(qs, "random_first", db2, max_rounds=max_rounds, rng=random.Random(rng.randint(0, 2**30)))

        results_db_first.append(r1)
        results_random_first.append(r2)

    agg1 = aggregate_runs(results_db_first)
    agg2 = aggregate_runs(results_random_first)

    return {
        "params": {
            "runs": runs,
            "n_questions": n_questions,
            "options_per_q": options_per_q,
            "initial_db_frac": initial_db_frac,
            "db_correct_frac": db_correct_frac,
            "max_rounds": max_rounds,
        },
        "db_first": agg1,
        "random_first": agg2,
    }


def print_report(report: dict):
    p = report["params"]
    print("--- Benchmark de simulación ---")
    print(f"Preguntas: {p['n_questions']}, opciones: {p['options_per_q']}, runs: {p['runs']}")
    print(f"DB inicial: {p['initial_db_frac']*100:.0f}% entradas; precisión DB: {p['db_correct_frac']*100:.0f}%")
    print("\nResultados promedio:")

    def fm(v):
        return f"{v:.2f}" if isinstance(v, float) else str(v)

    for key in ("avg_time_ms", "avg_rounds", "avg_solved", "avg_unsolved", "avg_db_hits", "avg_db_writes", "avg_mean_attempts", "avg_first_try_success"):
        a = report["db_first"][key]
        b = report["random_first"][key]
        print(f" - {key}: DB-first={fm(a)}    random-first={fm(b)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--questions", type=int, default=100)
    parser.add_argument("--options", type=int, default=4)
    parser.add_argument("--initial-db-frac", type=float, default=0.0)
    parser.add_argument("--db-correct-frac", type=float, default=1.0)
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    report = run_benchmark(
        runs=args.runs,
        n_questions=args.questions,
        options_per_q=args.options,
        initial_db_frac=args.initial_db_frac,
        db_correct_frac=args.db_correct_frac,
        max_rounds=args.max_rounds,
        seed=args.seed,
    )
    print_report(report)


if __name__ == "__main__":
    main()
