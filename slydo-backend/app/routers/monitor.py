"""
API 路由 — 监控仪表盘

提供：
1. /api/monitor/stats — 系统状态 JSON API
2. /dashboard — HTML 监控页面

每个文档的状态检测维度：
- PG（数据库）：有 decks + slides 记录 ✅
- 视觉分析（Vision）：slides 表中 visual_desc 非空的比例（视觉分析一定写 visual_desc）
- 缩略图（Thumbnail）：slides 表中 thumbnail_path 非空的比例
- Wiki：文件系统中存在对应的 Markdown 文件
- 向量化（Qdrant）：Qdrant 中有该 deck 的 points
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text, select

from app.config import settings
from app.database import async_session_factory
from app.models.deck import Deck
from app.qdrant import COLLECTION_NAME, get_qdrant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["监控"])


# ═══════════════════════════════════════════════════════════
# 1. HTML 监控页面
# ═══════════════════════════════════════════════════════════


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Slydo 入库监控</title>
<style>
  :root { --bg: #1a1b2e; --card: #232540; --accent: #6c63ff; --green: #4ade80; --yellow: #fbbf24; --red: #f87171; --text: #e2e8f0; --muted: #94a3b8; --orange: #fb923c; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 1280px; margin: 0 auto; padding: 24px; }
  header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; flex-wrap: wrap; gap: 12px; }
  h1 { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, var(--accent), #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .top-actions { display: flex; gap: 12px; align-items: center; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 24px; }
  .stat-card { background: var(--card); border-radius: 12px; padding: 18px; border: 1px solid #2d2f50; }
  .stat-card .label { font-size: 12px; color: var(--muted); margin-bottom: 6px; }
  .stat-card .value { font-size: 28px; font-weight: 700; }
  .stat-card .sub { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .section { background: var(--card); border-radius: 12px; margin-bottom: 16px; border: 1px solid #2d2f50; overflow: hidden; }
  .section-header { padding: 16px 20px 0; display: flex; justify-content: space-between; align-items: center; }
  .section-header h2 { font-size: 15px; font-weight: 600; color: var(--accent); }
  .section-body { padding: 12px 16px 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 10px 10px; text-align: left; border-bottom: 1px solid #2d2f50; white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
  tr:hover { background: rgba(108, 99, 255, 0.04); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; min-width: 46px; text-align: center; }
  .badge.ready { background: #166534; color: var(--green); }
  .badge.partial { background: #713f12; color: var(--yellow); }
  .badge.missing { background: #7f1d1d; color: var(--red); }
  .badge.progress { background: #2d1f5e; color: #a78bfa; }
  .badge.none { background: #334155; color: var(--muted); }
  .tag { display: inline-block; padding: 2px 6px; border-radius: 3px; font-size: 10px; background: #1e293b; color: var(--muted); margin-right: 3px; }
  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 40px; }
  .refresh-btn { background: var(--accent); color: white; border: none; padding: 7px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  .refresh-btn:hover { opacity: 0.9; }
  .last-update { font-size: 11px; color: var(--muted); }
  .loading { color: var(--muted); text-align: center; padding: 40px; }
  .disk-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
  .disk-item { background: var(--bg); border-radius: 8px; padding: 12px; border: 1px solid #2d2f50; }
  .disk-item .label { font-size: 11px; color: var(--muted); }
  .disk-item .size { font-size: 15px; font-weight: 600; margin-top: 4px; }
  .filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .filter-btn { padding: 4px 12px; border-radius: 6px; font-size: 11px; border: 1px solid #2d2f50; background: transparent; color: var(--muted); cursor: pointer; }
  .filter-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
  .tooltip { position: relative; cursor: help; }
  .tooltip:hover:after { content: attr(data-tip); position: absolute; bottom: 120%; left: 50%; transform: translateX(-50%); background: #1e293b; color: var(--text); padding: 4px 8px; border-radius: 4px; font-size: 11px; white-space: nowrap; z-index: 10; border: 1px solid #2d2f50; }
  .file-info { max-width: 200px; overflow: hidden; text-overflow: ellipsis; font-size: 11px; color: var(--muted); }
  .health-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .health-card { background: var(--bg); border-radius: 8px; padding: 14px; border: 1px solid #2d2f50; }
  .health-card .hdr { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .health-card .hdr .icon { font-size: 16px; }
  .health-card .hdr .name { font-size: 13px; font-weight: 600; }
  .health-card .status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-left: auto; }
  .health-card .status-dot.ok { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .health-card .status-dot.error { background: var(--red); box-shadow: 0 0 6px var(--red); }
  .health-card .info { font-size: 11px; color: var(--muted); }
  .health-card .info div { margin-top: 2px; }
  .health-card .info .key { color: var(--accent); }
  .health-card .error-msg { font-size: 11px; color: var(--red); margin-top: 4px; }
  @media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } .disk-grid { grid-template-columns: repeat(2, 1fr); } .health-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📊 Slydo 入库监控</h1>
    <div class="top-actions">
      <span class="last-update" id="lastUpdate">—</span>
      <button class="refresh-btn" onclick="fetchData()">🔄 刷新</button>
    </div>
  </header>

  <div id="statsGrid" class="stats-grid">
    <div class="stat-card">
      <div class="label">📁 文档总数</div>
      <div class="value" id="totalDecks">—</div>
      <div class="sub" id="totalSlides">页面数</div>
    </div>
    <div class="stat-card">
      <div class="label">🔍 向量化完成度</div>
      <div class="value" id="embedPct">—</div>
      <div class="sub" id="embedDetail">已向量化 / 总文档</div>
    </div>
    <div class="stat-card">
      <div class="label">👁️ 视觉分析完成度</div>
      <div class="value" id="visionPct">—</div>
      <div class="sub" id="visionDetail">已分析 / 总页面</div>
    </div>
    <div class="stat-card">
      <div class="label">📄 Wiki 文件</div>
      <div class="value" id="wikiFiles">—</div>
      <div class="sub">Markdown 文件</div>
    </div>
    <div class="stat-card">
      <div class="label">🖼️ 缩略图</div>
      <div class="value" id="thumbnailCount">—</div>
      <div class="sub">PNG 截图</div>
    </div>
    <div class="stat-card">
      <div class="label">⚙️ Qdrant 状态</div>
      <div class="value" id="qdrantStatus">—</div>
      <div class="sub" id="qdrantStatusDetail"></div>
    </div>
  </div>

  <div class="section">
    <div class="section-header">
      <h2>📋 文档入库详情</h2>
      <div class="filters" id="filterBar">
        <button class="filter-btn active" data-filter="all">全部</button>
        <button class="filter-btn" data-filter="incomplete">有缺失</button>
        <button class="filter-btn" data-filter="embedding">向量化中</button>
        <button class="filter-btn" data-filter="complete">已完成</button>
      </div>
    </div>
    <div class="section-body" id="deckTable">
      <div class="loading">加载中...</div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><h2>📂 存储空间</h2></div>
    <div class="section-body">
      <div class="disk-grid">
        <div class="disk-item"><div class="label">🗄️ PostgreSQL</div><div class="size" id="diskPG">—</div></div>
        <div class="disk-item"><div class="label">🔍 Qdrant 向量</div><div class="size" id="diskQdrant">—</div></div>
        <div class="disk-item"><div class="label">📄 Wiki</div><div class="size" id="diskWiki">—</div></div>
        <div class="disk-item"><div class="label">🖼️ 缩略图</div><div class="size" id="diskThumb">—</div></div>
      </div>
    </div>
    </div>
  </div>

  <div class="section">
    <div class="section-header"><h2>🔍 模块运行状态</h2></div>
    <div class="section-body">
      <div id="healthGrid" class="health-grid">
        <div class="loading">检测中...</div>
      </div>
    </div>
  </div>
</div>

<script>
let allDecks = [];

function statusBadge(status, label) {
  const cls = status === 2 ? 'ready' : status === 1 ? 'partial' : status === 0 ? 'missing' : 'none';
  return `<span class="badge ${cls}">${label}</span>`;
}

function renderTable(filter) {
  const tb = document.getElementById('deckTable');
  let decks = allDecks;
  
  if (filter === 'incomplete') {
    decks = decks.filter(d => !(d.embed_ready && d.vision_ready && d.wiki_ready && d.thumb_ready));
  } else if (filter === 'embedding') {
    decks = decks.filter(d => d.embed_progress < 100 || d.vision_progress < 100);
  } else if (filter === 'complete') {
    decks = decks.filter(d => d.embed_ready && d.vision_ready && d.wiki_ready && d.thumb_ready);
  }

  if (decks.length === 0) {
    tb.innerHTML = '<div class="empty">暂无匹配的文档</div>';
    return;
  }

  let html = `<table><thead><tr>
    <th>标题</th>
    <th class="tooltip" data-tip="PostgreSQL数据库">🗄️ PG</th>
    <th class="tooltip" data-tip="Qdrant向量嵌入">🔍 向量</th>
    <th class="tooltip" data-tip="Ollama视觉模型语义分析">👁️ 视觉</th>
    <th class="tooltip" data-tip="LLM Wiki Markdown文件">📄 Wiki</th>
    <th class="tooltip" data-tip="PNG页面截图">🖼️ 缩略图</th>
    <th>页数</th>
    <th>版本</th>
    <th>更新时间</th>
  </tr></thead><tbody>`;

  for (const d of decks) {
    const updated = d.updated_at ? new Date(d.updated_at).toLocaleString('zh-CN') : '—';
    
    // PG: always ready if in DB
    const pgBadge = statusBadge(2, '✅ 已入库');
    
    // 向量: 百分比
    const embedBadge = d.embed_ready 
      ? statusBadge(2, `${d.embed_progress}%`)
      : d.embed_progress > 0 
        ? statusBadge(1, `${d.embed_progress}%`)
        : statusBadge(0, `${d.embed_progress}%`);
    
    // 视觉: 百分比
    let visionLabel = `${d.vision_progress}%`;
    if (d.slide_count > 0 && d.vision_progress === 0) visionLabel = '跳过';
    const visionBadge = d.vision_ready 
      ? statusBadge(2, visionLabel)
      : d.vision_progress > 0 
        ? statusBadge(1, visionLabel)
        : statusBadge(0, visionLabel);
    
    // Wiki: 直接检查目录
    const wikiBadge = d.wiki_ready ? statusBadge(2, '✅ 已生成') : statusBadge(0, '❌ 缺失');
    
    // 缩略图: 百分比
    const thumbLabel = d.thumb_ready ? `${d.thumb_progress}%` : `${d.thumb_progress}%`;
    const thumbBadge = d.thumb_ready 
      ? statusBadge(2, thumbLabel)
      : d.thumb_progress > 0 
        ? statusBadge(1, thumbLabel)
        : statusBadge(0, thumbLabel);

    const title = escapeHtml(d.title);
    
    html += `<tr>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;" title="${title}"><strong>${title}</strong></td>
      <td>${pgBadge}</td>
      <td>${embedBadge}</td>
      <td>${visionBadge}</td>
      <td>${wikiBadge}</td>
      <td>${thumbBadge}</td>
      <td>${d.slide_count}</td>
      <td>v${d.version}</td>
      <td style="font-size:11px;color:var(--muted)">${updated}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  tb.innerHTML = html;
}

async function fetchData() {
  document.getElementById('lastUpdate').textContent = '刷新中...';
  const resp = await (await fetch('/api/monitor/stats')).json();
  if (resp.status !== 'ok') { alert('获取数据失败'); return; }
  const d = resp.data;

  document.getElementById('totalDecks').textContent = d.deck_count;
  document.getElementById('totalSlides').textContent = d.slide_count + ' 个页面';

  // 向量完成度
  const embedPct = d.deck_count > 0 ? Math.round(d.embedded_decks / d.deck_count * 100) : 0;
  document.getElementById('embedPct').textContent = embedPct + '%';
  document.getElementById('embedDetail').textContent = d.embedded_decks + ' / ' + d.deck_count + ' 个文档';

  // 视觉完成度
  const visionPct = d.slide_count > 0 ? Math.round(d.vision_slides / d.slide_count * 100) : 0;
  document.getElementById('visionPct').textContent = visionPct + '%';
  document.getElementById('visionDetail').textContent = d.vision_slides + ' / ' + d.slide_count + ' 页';

  document.getElementById('wikiFiles').textContent = d.wiki_files;
  document.getElementById('thumbnailCount').textContent = d.thumbnail_count;

  const qs = document.getElementById('qdrantStatus');
  const qdrantOk = d.qdrant_connected && d.qdrant_points > 0;
  qs.textContent = qdrantOk ? '✅ ' + d.qdrant_points : d.qdrant_connected ? '⚠️ 无数据' : '❌ 断开';
  qs.className = 'badge ' + (qdrantOk ? 'ready' : d.qdrant_connected ? 'partial' : 'missing');
  document.getElementById('qdrantStatusDetail').textContent = d.qdrant_info || '';

  document.getElementById('diskPG').textContent = d.disk_pg;
  document.getElementById('diskQdrant').textContent = d.disk_qdrant;
  document.getElementById('diskWiki').textContent = d.disk_wiki;
  document.getElementById('diskThumb').textContent = d.disk_thumbnails;

  allDecks = d.decks || [];
  const activeFilter = document.querySelector('.filter-btn.active');
  renderTable(activeFilter ? activeFilter.dataset.filter : 'all');

  document.getElementById('lastUpdate').textContent = '更新于 ' + new Date().toLocaleString('zh-CN');

  // 加载健康检测
  fetchHealthData();
}

async function fetchHealthData() {
  try {
    const resp = await (await fetch('/api/monitor/health')).json();
    const hg = document.getElementById('healthGrid');
    if (resp.status !== 'ok' && resp.status !== 'degraded') {
      hg.innerHTML = '<div class="empty">健康检测接口异常</div>';
      return;
    }
    renderHealth(resp);
  } catch (e) {
    document.getElementById('healthGrid').innerHTML = '<div class="empty">健康检测请求失败</div>';
  }
}

function renderHealth(data) {
  const hg = document.getElementById('healthGrid');
  const components = data.components;
  const icons = { postgresql: '🗄️', qdrant: '🔍', ollama: '⚡', libreoffice: '📄', filesystem: '💾', embedding_service: '🧠' };
  const names = { postgresql: 'PostgreSQL', qdrant: 'Qdrant', ollama: 'Ollama', libreoffice: 'LibreOffice', filesystem: '文件系统', embedding_service: '嵌入服务(bge-m3)' };

  let html = '';
  for (const [key, comp] of Object.entries(components)) {
    const isOk = comp.status === 'ok';
    const icon = icons[key] || '🔧';
    const name = names[key] || key;
    let infoHtml = '';
    if (isOk && comp.data) {
      for (const [k, v] of Object.entries(comp.data)) {
        const val = typeof v === 'object' ? JSON.stringify(v) : v;
        infoHtml += `<div><span class="key">${k}:</span> ${escapeHtml(String(val))}</div>`;
      }
    }
    if (!isOk && comp.detail) {
      infoHtml += `<div class="error-msg">❌ ${escapeHtml(comp.detail)}</div>`;
    }
    html += `<div class="health-card">
      <div class="hdr">
        <span class="icon">${icon}</span>
        <span class="name">${name}</span>
        <span class="status-dot ${isOk ? 'ok' : 'error'}"></span>
      </div>
      <div class="info">${infoHtml || '<div style="color:var(--muted)">无数据</div>'}</div>
    </div>`;
  }
  hg.innerHTML = html;
}

// 过滤器切换
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('filter-btn')) {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    renderTable(e.target.dataset.filter);
  }
});

function escapeHtml(text) {
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

fetchData();
setInterval(fetchData, 15000);
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Slydo 入库监控仪表盘"""
    return HTMLResponse(content=DASHBOARD_HTML, status_code=200)


# ═══════════════════════════════════════════════════════════
# 2. 统计数据 JSON API
# ═══════════════════════════════════════════════════════════


def _get_dir_size(path: str | Path) -> int:
    """获取目录总大小（字节）"""
    path = Path(path)
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.1f} GB"


@router.get("/api/monitor/stats")
async def monitor_stats():
    """获取系统监控统计数据"""
    wiki_root = Path(settings.slydo_wiki_path).expanduser()

    # ── PG 统计 ────────────────────────────────────────
    deck_count = 0
    slide_count = 0
    decks_list = []
    recently_added = 0
    embedded_decks = 0
    vision_slides = 0
    try:
        async with async_session_factory() as session:
            # 总数
            result = await session.execute(text("SELECT COUNT(*) FROM decks"))
            deck_count = result.scalar() or 0
            result = await session.execute(text("SELECT COUNT(*) FROM slides"))
            slide_count = result.scalar() or 0

            # 过去1小时入库
            result = await session.execute(
                text("SELECT COUNT(*) FROM decks WHERE created_at > NOW() - INTERVAL '1 hour'")
            )
            recently_added = result.scalar() or 0

            # 视觉分析进度（有 visual_desc 的 slide 数）
            result = await session.execute(text(
                "SELECT COUNT(*) FROM slides WHERE visual_desc IS NOT NULL AND visual_desc != ''"
            ))
            vision_slides = result.scalar() or 0

            # 每个 deck 的详细状态
            result = await session.execute(text("""
                SELECT
                    d.id::text,
                    d.title,
                    d.slide_count,
                    d.version,
                    d.created_at,
                    d.updated_at,
                    -- 向量：计数有 thumbnail_path 的 slide（Phase4 后 thumbnail_path 会被更新）
                    (SELECT COUNT(*) FROM slides s WHERE s.deck_id = d.id AND s.thumbnail_path IS NOT NULL
                     AND s.thumbnail_path != '') AS slides_with_thumb,
                    -- 视觉：有 visual_desc 的 slide 数
                    (SELECT COUNT(*) FROM slides s WHERE s.deck_id = d.id
                     AND s.visual_desc IS NOT NULL AND s.visual_desc != '') AS slides_with_vision,
                    -- 标题数（非空）
                    (SELECT COUNT(*) FROM slides s WHERE s.deck_id = d.id
                     AND s.title IS NOT NULL AND s.title != '') AS slides_with_title
                FROM decks d
                ORDER BY d.created_at DESC
                LIMIT 50
            """))

            # 预先查询 Qdrant 中有哪些 deck
            qdrant_deck_ids: set[str] = set()
            try:
                qdrant = get_qdrant()
                # Qdrant 不支持直接查所有 deck_id，用 scroll 采样
                scroll_result = qdrant.scroll(
                    collection_name=COLLECTION_NAME,
                    limit=10000,
                    with_payload=["deck_id"],
                    with_vectors=False,
                )
                for point in scroll_result[0]:
                    did = point.payload.get("deck_id", "")
                    if did:
                        qdrant_deck_ids.add(did)
            except Exception:
                pass

            # 检查 Wiki 目录
            slides_wiki_dir = wiki_root / "slides"

            for row in result.fetchall():
                deck_id_str = str(row.id)
                sc = row.slide_count or 0
                thumb_count = row.slides_with_thumb or 0
                vision_count = row.slides_with_vision or 0

                # 向量化：在 Qdrant 中查到该 deck_id
                has_qdrant = deck_id_str in qdrant_deck_ids
                if has_qdrant:
                    embedded_decks += 1

                # Wiki：检查 /slides/deck_{id} 目录是否存在且有 .md 文件
                deck_wiki_dir = slides_wiki_dir / f"deck_{deck_id_str}"
                wiki_ready = deck_wiki_dir.exists() and len(list(deck_wiki_dir.glob("*.md"))) > 0

                # 计算各自的百分比
                thumb_pct = round(thumb_count / sc * 100) if sc > 0 else 0
                vision_pct = round(vision_count / sc * 100) if sc > 0 else 0

                decks_list.append({
                    "title": row.title or "",
                    "slide_count": sc,
                    "version": row.version or 1,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "updated_at": row.updated_at.isoformat() if row.updated_at else "",
                    # 向量
                    "embed_ready": has_qdrant,
                    "embed_progress": 100 if has_qdrant else 0,
                    # 视觉
                    "vision_ready": sc > 0 and vision_count == sc,
                    "vision_progress": vision_pct,
                    # Wiki
                    "wiki_ready": wiki_ready,
                    # 缩略图
                    "thumb_ready": sc > 0 and thumb_count == sc,
                    "thumb_progress": thumb_pct,
                })
    except Exception as e:
        logger.warning(f"PG 统计失败: {e}")

    # ── Qdrant 统计 ────────────────────────────────────
    qdrant_connected = False
    qdrant_points = 0
    qdrant_info = ""
    try:
        qdrant = get_qdrant()
        info = qdrant.get_collection(COLLECTION_NAME)
        qdrant_points = info.points_count
        qdrant_connected = True
        qdrant_info = f"collection: {COLLECTION_NAME}"
    except Exception as e:
        qdrant_info = str(e)[:100]

    # ── Wiki 文件统计 ──────────────────────────────────
    wiki_files = 0
    try:
        if wiki_root.exists():
            wiki_files = len(list(wiki_root.rglob("*.md")))
    except Exception:
        pass

    # ── 缩略图统计 ────────────────────────────────────
    thumbnail_count = 0
    thumb_dir = wiki_root / "thumbnails"
    try:
        if thumb_dir.exists():
            thumbnail_count = len(list(thumb_dir.rglob("*.png")))
    except Exception:
        pass

    # ── 磁盘占用 ───────────────────────────────────────
    qdrant_dir = Path(settings.qdrant_path).expanduser()
    disk_qdrant = _format_size(_get_dir_size(qdrant_dir)) if qdrant_dir.exists() else "—"
    disk_wiki = _format_size(_get_dir_size(wiki_root / "slides")) if (wiki_root / "slides").exists() else "—"
    disk_thumbnails = _format_size(_get_dir_size(thumb_dir)) if thumb_dir.exists() else "—"
    # PG 磁盘 → 近似估算，Docker 容器内不可见则跳过
    pg_dir = Path("/var/lib/postgresql/16/main")
    disk_pg = _format_size(_get_dir_size(pg_dir)) if pg_dir.exists() else "—"
    if disk_pg == "0 B":
        disk_pg = "—"

    return {
        "status": "ok",
        "data": {
            "deck_count": deck_count,
            "slide_count": slide_count,
            "recently_added": recently_added,
            "embedded_decks": embedded_decks,
            "vision_slides": vision_slides,
            "decks": decks_list,
            "qdrant_connected": qdrant_connected,
            "qdrant_points": qdrant_points,
            "qdrant_info": qdrant_info,
            "wiki_files": wiki_files,
            "thumbnail_count": thumbnail_count,
            "disk_pg": disk_pg,
            "disk_qdrant": disk_qdrant,
            "disk_wiki": disk_wiki,
            "disk_thumbnails": disk_thumbnails,
        },
    }


# ═══════════════════════════════════════════════════════════
# 3. 组件健康检测 API
# 3. 组件健康检测 API
# ═══════════════════════════════════════════════════════════


async def _check_pg() -> dict:
    """检测 PostgreSQL 连接和状态"""
    result = {"status": "error", "detail": "", "data": {}}
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
            r = await session.execute(text("SELECT count(*) FROM decks"))
            deck_count = r.scalar() or 0
            r = await session.execute(text("SELECT count(*) FROM slides"))
            slide_count = r.scalar() or 0
            # DB size
            r = await session.execute(text(
                "SELECT pg_size_pretty(pg_database_size('slydo'))"
            ))
            db_size = r.scalar() or "?"
            result["status"] = "ok"
            result["data"] = {
                "decks": deck_count,
                "slides": slide_count,
                "db_size": db_size,
            }
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


async def _check_qdrant() -> dict:
    """检测 Qdrant 连接和集合状态"""
    result = {"status": "error", "detail": "", "data": {}}
    try:
        qdrant = get_qdrant()
        info = qdrant.get_collection(COLLECTION_NAME)
        result["status"] = "ok"
        result["data"] = {
            "points": info.points_count,
            "vectors_config": str(info.config.params.vectors),
            "status": str(info.status),
        }
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


async def _check_llm_api() -> dict:
    """检测云端 LLM API（DeepSeek）是否可用"""
    import httpx
    result = {"status": "error", "detail": "", "data": {}}
    try:
        base = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        key = settings.deepseek_api_key or ""
        model = settings.llm_model or "deepseek-chat"
        # 简化验证：轻量请求测试连通性
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5},
            )
            if r.status_code == 200:
                result["status"] = "ok"
                result["data"] = {"model": model, "provider": "DeepSeek"}
            else:
                result["detail"] = f"HTTP {r.status_code}"
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


async def _check_libreoffice() -> dict:
    """检测 LibreOffice 是否可用"""
    import subprocess
    result = {"status": "error", "detail": "", "data": {}}
    try:
        r = subprocess.run(
            ["libreoffice", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            result["status"] = "ok"
            result["data"] = {"version": r.stdout.strip()}
        else:
            result["detail"] = r.stderr[:100]
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


async def _check_filesystem() -> dict:
    """检测文件系统状态"""
    import shutil
    result = {"status": "ok", "detail": "", "data": {}}
    try:
        wiki_root = Path(settings.slydo_wiki_path).expanduser()
        # 检查关键目录是否存在
        dirs = {
            "wiki_root": wiki_root,
            "wiki_slides": wiki_root / "slides",
            "wiki_decks": wiki_root / "decks",
            "thumbnails": wiki_root / "thumbnails",
        }
        dir_status = {}
        for name, p in dirs.items():
            dir_status[name] = {"exists": p.exists()}

        # Wiki 文件数
        md_files = 0
        if wiki_root.exists():
            md_files = len(list(wiki_root.rglob("*.md")))

        # 磁盘空间
        total, used, free = shutil.disk_usage(wiki_root if wiki_root.exists() else Path.home())
        free_gb = free / (1024**3)

        # 监视目录
        watch_dir = None
        for candidate in ["/mnt/c/Users/kiven/Documents/个人知识库/Coding/Slydo/slydo-watch", "/root/slydo-watch", "~/slydo-watch"]:
            p = Path(candidate).expanduser()
            if p.exists():
                watch_dir = str(p)
                pptx_count = len(list(p.rglob("*.pptx")) + list(p.rglob("*.ppt")))
                break

        result["data"] = {
            "directories": dir_status,
            "wiki_md_files": md_files,
            "disk_free_gb": round(free_gb, 1),
            "watch_dir": watch_dir or "not found",
            "watch_pptx_count": pptx_count if watch_dir else 0,
        }
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


async def _check_vl_api() -> dict:
    """检测云端视觉模型 API（DeepSeek VL / DashScope Qwen-VL）"""
    import httpx
    result = {"status": "error", "detail": "", "data": {}}
    # 优先检测 DashScope（阿里云 Qwen-VL），作为视觉 API 的代表
    try:
        dashscope_key = settings.dashscope_api_key or ""
        dashscope_base = settings.dashscope_base_url or "https://dashscope.aliyuncs.com/api/v1"
        vl_model = settings.dashscope_vision_model or "qwen-vl-plus"
        if dashscope_key:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(
                    f"{dashscope_base}/services/aigc/multimodal-generation/generation",
                    headers={"Authorization": f"Bearer {dashscope_key}", "Content-Type": "application/json"},
                    json={
                        "model": vl_model,
                        "input": {"messages": [{"role": "user", "content": [{"text": "ping"}]}]},
                    },
                )
                if r.status_code == 200:
                    result["status"] = "ok"
                    result["data"] = {"model": vl_model, "provider": "DashScope/Aliyun"}
                else:
                    result["detail"] = f"HTTP {r.status_code}"
        else:
            result["detail"] = "未配置 DashScope API Key"
    except Exception as e:
        err_msg = str(e)[:100] or type(e).__name__
        result["detail"] = err_msg
    return result


@router.get("/api/monitor/health")
async def monitor_health():
    """获取所有组件健康状态"""
    import asyncio
    results = await asyncio.gather(
        _check_pg(),
        _check_qdrant(),
        _check_llm_api(),
        _check_libreoffice(),
        _check_filesystem(),
        _check_vl_api(),
        return_exceptions=True,
    )
    pg_result, qdrant_result, llm_result, lo_result, fs_result, vl_result = results

    # 处理异常（方法内的异常会返回 Exception 对象）
    def safe(r, default=None):
        return r if isinstance(r, dict) else (default or {"status": "error", "detail": str(r)[:100], "data": {}})

    pg_result = safe(pg_result)
    qdrant_result = safe(qdrant_result)
    llm_result = safe(llm_result)
    lo_result = safe(lo_result)
    fs_result = safe(fs_result)
    vl_result = safe(vl_result)

    all_ok = all(
        r["status"] == "ok"
        for r in [pg_result, qdrant_result, llm_result, lo_result, fs_result, vl_result]
    )

    return {
        "status": "ok" if all_ok else "degraded",
        "timestamp": __import__("datetime").datetime.now().isoformat(),
        "components": {
            "postgresql": pg_result,
            "qdrant": qdrant_result,
            "llm_api": llm_result,
            "libreoffice": lo_result,
            "filesystem": fs_result,
            "vl_api": vl_result,
        },
    }
