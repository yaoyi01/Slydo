"""
API 路由 — 使用统计仪表盘页面

提供 HTML 页面供公司内部查看各页面/文档使用情况。
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["使用统计面板"])

USAGE_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Slydo 页面使用统计</title>
<style>
  :root { --bg: #1a1b2e; --card: #232540; --accent: #6c63ff; --green: #4ade80; --yellow: #fbbf24; --red: #f87171; --text: #e2e8f0; --muted: #94a3b8; --orange: #fb923c; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 1280px; margin: 0 auto; padding: 24px; }
  header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 28px; flex-wrap: wrap; gap: 12px; }
  h1 { font-size: 24px; font-weight: 700; background: linear-gradient(135deg, #f59e0b, #ef4444); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .nav-tabs { display: flex; gap: 8px; margin-bottom: 20px; }
  .nav-tab { padding: 8px 16px; border-radius: 8px; font-size: 13px; border: 1px solid #2d2f50; background: transparent; color: var(--muted); cursor: pointer; }
  .nav-tab.active { background: var(--accent); color: white; border-color: var(--accent); }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-bottom: 24px; }
  .stat-card { background: var(--card); border-radius: 12px; padding: 18px; border: 1px solid #2d2f50; text-align: center; }
  .stat-card .label { font-size: 11px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.3px; }
  .stat-card .value { font-size: 32px; font-weight: 700; }
  .stat-card .sub { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .section { background: var(--card); border-radius: 12px; margin-bottom: 16px; border: 1px solid #2d2f50; overflow: hidden; }
  .section-header { padding: 16px 20px 8px; display: flex; justify-content: space-between; align-items: center; }
  .section-header h2 { font-size: 15px; font-weight: 600; color: var(--accent); }
  .section-body { padding: 8px 16px 16px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { padding: 10px 10px; text-align: left; border-bottom: 1px solid #2d2f50; }
  th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
  tr:hover { background: rgba(108, 99, 255, 0.04); }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 500; }
  .badge.hot { background: #7f1d1d; color: var(--red); }
  .badge.warm { background: #713f12; color: var(--yellow); }
  .badge.cool { background: #1e3a5f; color: #60a5fa; }
  .badge.cold { background: #334155; color: var(--muted); }
  .bar-wrap { background: #1e293b; border-radius: 4px; height: 8px; min-width: 60px; }
  .bar-fill { height: 8px; border-radius: 4px; background: linear-gradient(90deg, var(--accent), #a78bfa); }
  .trend-chart { display: flex; gap: 2px; align-items: flex-end; height: 40px; }
  .trend-bar { width: 100%; border-radius: 2px 2px 0 0; background: var(--accent); min-height: 2px; }
  .empty { color: var(--muted); font-size: 13px; text-align: center; padding: 40px; }
  .top-actions { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .refresh-btn { background: var(--accent); color: white; border: none; padding: 7px 18px; border-radius: 8px; cursor: pointer; font-size: 13px; }
  .refresh-btn:hover { opacity: 0.9; }
  .last-update { font-size: 11px; color: var(--muted); }
  .period-select { background: #1e293b; color: var(--text); border: 1px solid #2d2f50; border-radius: 6px; padding: 6px 12px; font-size: 12px; }
  .loading { color: var(--muted); text-align: center; padding: 60px; font-size: 14px; }
  @media (max-width: 768px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>📈 PPT 素材使用统计</h1>
    <div class="top-actions">
      <select class="period-select" id="periodSelect" onchange="loadData()">
        <option value="7">近 7 天</option>
        <option value="30" selected>近 30 天</option>
        <option value="90">近 90 天</option>
        <option value="365">近 1 年</option>
      </select>
      <span class="last-update" id="lastUpdate">—</span>
      <button class="refresh-btn" onclick="loadData()">🔄 刷新</button>
    </div>
  </header>

  <div class="nav-tabs">
    <button class="nav-tab active" data-tab="pages">📄 页面排行</button>
    <button class="nav-tab" data-tab="decks">📁 文档排行</button>
    <button class="nav-tab" data-tab="search">🔍 搜索热词</button>
  </div>

  <div id="statsGrid" class="stats-grid">
    <div class="stat-card"><div class="label">总使用次数</div><div class="value" id="totalLogs">—</div><div class="sub">搜索+浏览+导入</div></div>
    <div class="stat-card"><div class="label">使用页面数</div><div class="value" id="uniqueSlides">—</div><div class="sub">有被查看/导入</div></div>
    <div class="stat-card"><div class="label">使用用户数</div><div class="value" id="uniqueUsers">—</div><div class="sub">不同操作者</div></div>
    <div class="stat-card"><div class="label">搜索次数</div><div class="value" id="searchCount">—</div><div class="sub">用户主动搜索</div></div>
  </div>

  <!-- 页面排行 -->
  <div id="tabPages" class="section">
    <div class="section-header"><h2>📄 热门页面 TOP 20</h2></div>
    <div class="section-body" id="pagesTable"><div class="loading">加载中...</div></div>
  </div>

  <!-- 文档排行 -->
  <div id="tabDecks" class="section" style="display:none">
    <div class="section-header"><h2>📁 热门文档 TOP 20</h2></div>
    <div class="section-body" id="decksTable"><div class="loading">加载中...</div></div>
  </div>

  <!-- 搜索热词 -->
  <div id="tabSearch" class="section" style="display:none">
    <div class="section-header"><h2>🔍 搜索热词 TOP 20</h2></div>
    <div class="section-body" id="searchTable"><div class="loading">加载中...</div></div>
  </div>
</div>

<script>
function escapeHtml(t) {
  const d = document.createElement('div'); d.textContent = t; return d.innerHTML;
}

function usageBadge(count) {
  if (count >= 10) return '<span class="badge hot">🔥 热门</span>';
  if (count >= 5) return '<span class="badge warm">⚡ 热门</span>';
  if (count >= 2) return '<span class="badge cool">• 一般</span>';
  return '<span class="badge cold">○ 偶尔</span>';
}

function barWidth(count, maxCount) {
  const pct = maxCount > 0 ? Math.round(count / maxCount * 100) : 0;
  return Math.max(pct, 2);
}

async function loadData() {
  document.getElementById('lastUpdate').textContent = '加载中...';
  const days = document.getElementById('periodSelect').value;

  try {
    const resp = await (await fetch(`/api/usage/stats?days=${days}&limit=20`)).json();
    if (resp.status !== 'ok') { alert('获取数据失败'); return; }
    const d = resp.data;

    // 统计卡
    document.getElementById('totalLogs').textContent = d.overview.total_logs;
    document.getElementById('uniqueSlides').textContent = d.overview.unique_slides;
    document.getElementById('uniqueUsers').textContent = d.overview.unique_users;

    const searchAction = (d.by_action || []).find(a => a.action === 'search');
    document.getElementById('searchCount').textContent = searchAction ? searchAction.count : 0;

    // 页面排行
    const pages = d.top_slides || [];
    renderPages(pages);

    // 文档排行
    const decks = d.top_decks || [];
    renderDecks(decks);

    // 搜索热词
    const queries = d.top_queries || [];
    renderQueries(queries);

    document.getElementById('lastUpdate').textContent = new Date().toLocaleString('zh-CN');
  } catch (e) {
    document.getElementById('lastUpdate').textContent = '❌ 加载失败';
  }
}

function renderPages(pages) {
  const tb = document.getElementById('pagesTable');
  if (pages.length === 0) {
    tb.innerHTML = '<div class="empty">暂无使用记录</div>';
    return;
  }
  const maxCount = Math.max(...pages.map(p => p.usage_count), 1);
  let html = `<table><thead><tr>
    <th>#</th>
    <th>页面标题</th>
    <th>所属文档</th>
    <th>使用次数</th>
    <th>热度</th>
    <th>使用占比</th>
  </tr></thead><tbody>`;
  pages.forEach((p, i) => {
    const bw = barWidth(p.usage_count, maxCount);
    html += `<tr>
      <td>${i + 1}</td>
      <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(p.title)}">
        <strong>${escapeHtml(p.title || '(无标题)')}</strong>
      </td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(p.deck_title)}">
        ${escapeHtml(p.deck_title || '—')}
      </td>
      <td><strong>${p.usage_count}</strong></td>
      <td>${usageBadge(p.usage_count)}</td>
      <td>
        <div class="bar-wrap"><div class="bar-fill" style="width:${bw}%"></div></div>
      </td>
    </tr>`;
  });
  html += '</tbody></table>';
  tb.innerHTML = html;
}

function renderDecks(decks) {
  const tb = document.getElementById('decksTable');
  if (decks.length === 0) {
    tb.innerHTML = '<div class="empty">暂无使用记录</div>';
    return;
  }
  const maxCount = Math.max(...decks.map(d => d.total_usage), 1);
  let html = `<table><thead><tr>
    <th>#</th>
    <th>文档名称</th>
    <th>部门</th>
    <th>使用次数</th>
    <th>覆盖面</th>
    <th>趋势</th>
  </tr></thead><tbody>`;
  decks.forEach((d, i) => {
    const bw = barWidth(d.total_usage, maxCount);
    const covLabel = d.coverage_pct + '%';
    const covBar = barWidth(d.coverage_pct, 100);
    html += `<tr>
      <td>${i + 1}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(d.title)}">
        <strong>${escapeHtml(d.title)}</strong>
      </td>
      <td>${escapeHtml(d.dept || '—')}</td>
      <td><strong>${d.total_usage}</strong></td>
      <td>${d.used_slides}/${d.slide_count} 页 (${covLabel})
        <div class="bar-wrap"><div class="bar-fill" style="width:${covBar}%"></div></div>
      </td>
      <td>${usageBadge(d.total_usage)}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  tb.innerHTML = html;
}

function renderQueries(queries) {
  const tb = document.getElementById('searchTable');
  if (queries.length === 0) {
    tb.innerHTML = '<div class="empty">暂无搜索记录</div>';
    return;
  }
  const maxCount = Math.max(...queries.map(q => q.count), 1);
  let html = `<table><thead><tr>
    <th>#</th>
    <th>搜索关键词</th>
    <th>搜索次数</th>
    <th>占比</th>
  </tr></thead><tbody>`;
  queries.forEach((q, i) => {
    const bw = barWidth(q.count, maxCount);
    html += `<tr>
      <td>${i + 1}</td>
      <td><strong>${escapeHtml(q.query)}</strong></td>
      <td>${q.count}</td>
      <td><div class="bar-wrap"><div class="bar-fill" style="width:${bw}%"></div></div></td>
    </tr>`;
  });
  html += '</tbody></table>';
  tb.innerHTML = html;
}

// 标签页切换
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('nav-tab')) {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    e.target.classList.add('active');
    const tab = e.target.dataset.tab;
    ['pages', 'decks', 'search'].forEach(t => {
      document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1)).style.display = t === tab ? '' : 'none';
    });
  }
});

loadData();
</script>
</body>
</html>
"""


@router.get("/usage-dashboard", response_class=HTMLResponse)
async def usage_dashboard_page():
    """PPT 素材使用统计仪表盘"""
    return HTMLResponse(content=USAGE_DASHBOARD_HTML, status_code=200)
