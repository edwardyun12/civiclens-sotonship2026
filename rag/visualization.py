"""Interactive visualisations for retrieved evidence."""

from __future__ import annotations

import html
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import streamlit.components.v1 as components

from rag.config import INDEX_FILE, PROJECT_ROOT


@lru_cache(maxsize=4)
def _project_index(index_path: str, modified_at: float) -> list[dict]:
    """Project indexed embeddings into two dimensions with PCA via SVD."""
    del modified_at
    payload = json.loads(Path(index_path).read_text(encoding="utf-8"))
    records = [
        record
        for record in payload.get("records", [])
        if (PROJECT_ROOT / record["source"]).is_file()
    ]
    if not records:
        return []

    embeddings = np.asarray([record["embedding"] for record in records], dtype=float)
    centred = embeddings - embeddings.mean(axis=0, keepdims=True)
    if len(records) == 1:
        projected = np.zeros((1, 2), dtype=float)
    else:
        _, _, components_ = np.linalg.svd(centred, full_matrices=False)
        dimensions = min(2, components_.shape[0])
        projected = centred @ components_[:dimensions].T
        if dimensions == 1:
            projected = np.column_stack([projected[:, 0], np.zeros(len(records))])

    coordinates = []
    for axis in range(2):
        values = projected[:, axis]
        low, high = float(values.min()), float(values.max())
        if high - low < 1e-12:
            coordinates.append(np.full(len(records), 50.0))
        else:
            coordinates.append(7.0 + ((values - low) / (high - low)) * 86.0)

    return [
        {
            "source": record["source"],
            "chunk": record["chunk"],
            "text": " ".join(record["text"].split()),
            "x": float(coordinates[0][index]),
            "y": float(coordinates[1][index]),
        }
        for index, record in enumerate(records)
    ]


def render_evidence_universe(question: str, sources: list[dict]) -> None:
    """Render all indexed chunks and highlight the chunks selected for the answer."""
    if not sources or not INDEX_FILE.exists():
        return

    projected = _project_index(str(INDEX_FILE), INDEX_FILE.stat().st_mtime)
    selected = {
        (source["source"], source["chunk"]): (rank, source)
        for rank, source in enumerate(sources, start=1)
    }
    palette = ["#22d3ee", "#a78bfa", "#fb923c", "#4ade80", "#fb7185"]
    points = []
    for record in projected:
        selection = selected.get((record["source"], record["chunk"]))
        rank = selection[0] if selection else None
        source = selection[1] if selection else None
        preview = record["text"]
        if len(preview) > 300:
            preview = f"{preview[:297]}..."
        points.append(
            {
                **record,
                "preview": preview,
                "selected": source is not None,
                "rank": rank,
                "citation": source["citation"] if source else Path(record["source"]).stem,
                "vector": source["vector_score"] if source else None,
                "bm25": source["bm25_score"] if source else None,
                "hybrid": source["rrf_score"] if source else None,
                "colour": palette[(rank - 1) % len(palette)] if rank else "#52708f",
            }
        )

    safe_question = html.escape(question)
    points_json = json.dumps(points).replace("</", "<\\/")
    components.html(
        f"""
        <style>
          * {{ box-sizing: border-box; }}
          body {{ margin:0; font-family:Inter,ui-sans-serif,system-ui,sans-serif; }}
          .map {{ position:relative; height:480px; overflow:hidden; border-radius:22px;
            border:1px solid #1e3a5f; color:#e5f3ff;
            background:linear-gradient(145deg,#07111f,#0a1830 60%,#0c1427); }}
          .grid {{ position:absolute; inset:0; opacity:.22; background-image:
            linear-gradient(#60a5fa 1px,transparent 1px),linear-gradient(90deg,#60a5fa 1px,transparent 1px);
            background-size:48px 48px; }}
          .header {{ position:absolute; z-index:6; top:18px; left:22px; max-width:70%; }}
          .eyebrow {{ color:#67e8f9; font-size:10px; font-weight:800; letter-spacing:.17em; }}
          h3 {{ margin:4px 0 3px; font-size:19px; }}
          .query {{ color:#9fb3ca; font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
          .plot {{ position:absolute; inset:73px 24px 40px 48px; border-left:1px solid #35516e;
            border-bottom:1px solid #35516e; }}
          .axis {{ position:absolute; color:#6e829b; font:9px monospace; letter-spacing:.1em; }}
          .axis.x {{ bottom:12px; left:50%; }} .axis.y {{ top:51%; left:9px; transform:rotate(-90deg); }}
          .point {{ position:absolute; transform:translate(-50%,50%); width:8px; height:8px;
            padding:0; border:0; border-radius:50%; cursor:pointer; background:#52708f;
            box-shadow:0 0 5px #52708f55; transition:transform .15s,filter .15s; }}
          .point:hover {{ transform:translate(-50%,50%) scale(1.8); filter:brightness(1.5); z-index:7; }}
          .point.selected {{ width:22px; height:22px; color:#07111f; font-size:10px; font-weight:900;
            background:var(--colour); box-shadow:0 0 18px var(--colour); z-index:5;
            border:2px solid #e8fbff; }}
          .point.selected:hover {{ transform:translate(-50%,50%) scale(1.2); }}
          .legend {{ position:absolute; right:18px; top:18px; color:#9fb3ca; font-size:10px; z-index:6; }}
          .legend span {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin:0 5px 0 12px; }}
          .detail {{ display:none; position:absolute; z-index:9; right:17px; bottom:17px; width:min(390px,48%);
            padding:13px 15px; border-radius:14px; background:rgba(6,16,30,.95);
            border:1px solid #345577; box-shadow:0 14px 30px #0007; }}
          .detail.show {{ display:block; }}
          .detail-title {{ font-size:12px; font-weight:800; color:#fff; margin-bottom:6px; }}
          .detail-copy {{ font-size:10px; line-height:1.42; color:#b6c5d8; }}
          .scores {{ display:flex; gap:10px; margin-top:8px; color:#67e8f9; font:9px monospace; }}
          @media(max-width:700px) {{ .map{{height:510px}} .detail{{left:16px;right:16px;width:auto}} .legend{{display:none}} }}
        </style>
        <div class="map">
          <div class="grid"></div>
          <div class="header"><div class="eyebrow">SEMANTIC RETRIEVAL</div><h3>PCA 2D Vector Map</h3>
            <div class="query">Query: {safe_question}</div></div>
          <div class="legend"><span style="background:#52708f"></span>All chunks
            <span style="background:#22d3ee"></span>Retrieved chunks</div>
          <div class="plot" id="plot"></div>
          <div class="axis x">PCA 1</div><div class="axis y">PCA 2</div>
          <div class="detail" id="detail"></div>
        </div>
        <script>
          const points = {points_json};
          const plot = document.getElementById('plot');
          const detail = document.getElementById('detail');
          const esc = value => String(value).replace(/[&<>"']/g, char => ({{
            '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#039;'
          }})[char]);
          points.forEach(point => {{
            const button = document.createElement('button');
            button.className = `point${{point.selected ? ' selected' : ''}}`;
            button.style.left = `${{point.x}}%`; button.style.bottom = `${{point.y}}%`;
            button.style.setProperty('--colour', point.colour);
            button.textContent = point.rank || '';
            button.setAttribute('aria-label', `${{point.selected ? 'Retrieved' : 'Indexed'}} chunk: ${{point.citation}}`);
            button.addEventListener('click', () => {{
              const scoreMarkup = point.selected ? `<div class="scores"><span>VECTOR ${{point.vector.toFixed(3)}}</span>
                <span>BM25 ${{point.bm25.toFixed(3)}}</span><span>RRF ${{point.hybrid.toFixed(4)}}</span></div>` : '';
              detail.innerHTML = `<div class="detail-title">${{point.selected ? `Retrieved #${{point.rank}} · ` : ''}}${{esc(point.citation)}}</div>
                <div class="detail-copy">Chunk ${{point.chunk}} · ${{esc(point.preview)}}</div>${{scoreMarkup}}`;
              detail.classList.add('show');
            }});
            plot.appendChild(button);
          }});
        </script>
        """,
        height=495,
        scrolling=False,
    )
