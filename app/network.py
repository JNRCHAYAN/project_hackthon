"""Cross-provider network and relationship insight.

The question this answers: *the same account is moving money at three different
outlets — is that one customer's business, or a coordinated pattern across
outlets that no single outlet can see?*

Account identifiers are already hashed upstream; this module never receives a
raw identifier. Nothing here compares agents against each other — nodes are
accounts and their outlets, not people, and the output is a structural map for a
human analyst, not a verdict.

The metric that matters is **concentration**: a shared account whose activity is
funnelled through very few outlets is structurally different from one spread
thinly across many, and only the former is worth an analyst's time.
"""
from __future__ import annotations

from collections import defaultdict

from app.config import SETTINGS
from app.domain import NetworkEdge, NetworkNode

CONCENTRATION_TOP_SHARE = 0.7


def build_graph(states: dict) -> tuple[list[NetworkNode], list[NetworkEdge]]:
    """Nodes are shared accounts; edges link the outlets they appear in.

    ``states`` maps outlet_id -> OutletState.
    """
    accounts: dict[str, dict] = defaultdict(
        lambda: {"outlets": set(), "providers": set(), "count": 0, "value": 0.0,
                 "by_outlet": defaultdict(float)})

    for outlet_id, state in states.items():
        for t in state.transactions:
            if t.status != "success":
                continue
            entry = accounts[t.sender_hash]
            entry["outlets"].add(outlet_id)
            entry["providers"].add(t.provider_id)
            entry["count"] += 1
            entry["value"] += t.amount
            entry["by_outlet"][outlet_id] += t.amount

    nodes: list[NetworkNode] = []
    edges: dict[tuple[str, str], NetworkEdge] = {}

    for account_hash, entry in accounts.items():
        if len(entry["outlets"]) < SETTINGS["network_min_shared_accounts"]:
            continue

        total = entry["value"] or 1.0
        top_share = max(entry["by_outlet"].values()) / total

        nodes.append(NetworkNode(
            account_hash=account_hash,
            outlet_ids=sorted(entry["outlets"]),
            provider_ids=sorted(entry["providers"]),
            txn_count=entry["count"],
            total_value=round(entry["value"], 2),
            is_concentrated=top_share >= CONCENTRATION_TOP_SHARE,
        ))

        # Edges connect the outlets this account moves through.
        ordered = sorted(entry["outlets"])
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                key = (ordered[i], ordered[j])
                if key not in edges:
                    edges[key] = NetworkEdge(source=ordered[i], target=ordered[j],
                                             shared_txns=0,
                                             providers=sorted(entry["providers"]))
                edges[key].shared_txns += entry["count"]

    nodes.sort(key=lambda n: (not n.is_concentrated, -n.txn_count))
    edge_list = sorted(edges.values(), key=lambda e: -e.shared_txns)
    return nodes, edge_list


def cross_provider_patterns(states: dict) -> list[dict]:
    """Accounts active on more than one provider — the pattern no single
    provider's own dashboard can see. Advisory only; these are ordinary
    customers more often than not."""
    per_account: dict[str, set[str]] = defaultdict(set)
    for state in states.values():
        for t in state.transactions:
            if t.status == "success":
                per_account[t.sender_hash].add(t.provider_id)

    patterns = []
    for account_hash, providers in per_account.items():
        if len(providers) > 1:
            patterns.append({
                "account_hash": account_hash,
                "providers": sorted(providers),
                "provider_count": len(providers),
            })
    patterns.sort(key=lambda p: (-p["provider_count"], p["account_hash"]))
    return patterns


def summarise(nodes: list[NetworkNode], edges: list[NetworkEdge]) -> dict:
    concentrated = [n for n in nodes if n.is_concentrated]
    return {
        "shared_accounts": len(nodes),
        "concentrated_accounts": len(concentrated),
        "links": len(edges),
        "note": ("Accounts appearing at "
                 f"{SETTINGS['network_min_shared_accounts']}+ outlets are shown. "
                 "A shared account is usually an ordinary customer who banks "
                 "across several outlets."),
    }
