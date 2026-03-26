/* =========================================================
   OVERMIND DASHBOARD — app.js
   ========================================================= */

const API = window.location.origin;
let currentRepo = '';
let graphData = null;
let timelineData = null;

// --- Color palette ---
const C = {
    correction: '#ff4757', decision: '#ffa235', discovery: '#a78bfa',
    change: '#00e5a0', broadcast: '#f472b6',
    user: '#38bdf8', scope: '#5a6a7e', accent: '#00e5a0',
};

// --- Tab switching ---
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
        if (currentRepo) {
            if (btn.dataset.tab === 'graph') renderGraph(graphData);
            if (btn.dataset.tab === 'timeline') renderTimeline(timelineData);
        }
    });
});

// --- Repo loading ---
(async function loadRepos() {
    const res = await fetch(`${API}/api/repos`);
    const repos = await res.json();
    const sel = document.getElementById('repo-id');
    sel.innerHTML = '<option value="">select repository</option>';
    repos.forEach(r => {
        const o = document.createElement('option');
        o.value = r; o.textContent = r;
        sel.appendChild(o);
    });
    if (repos.length === 1) { sel.value = repos[0]; loadAll(); }
})();

async function loadAll() {
    currentRepo = document.getElementById('repo-id').value;
    if (!currentRepo) return;
    await Promise.all([loadOverview(), loadGraphData(), loadTimelineData()]);
}

// ============================================================
// OVERVIEW
// ============================================================
async function loadOverview() {
    const [repRes, pullRes] = await Promise.all([
        fetch(`${API}/api/report?repo_id=${enc(currentRepo)}`),
        fetch(`${API}/api/memory/pull?repo_id=${enc(currentRepo)}&limit=30`),
    ]);
    const report = await repRes.json();
    const pull = await pullRes.json();

    animateNumber('stat-pushes', report.total_pushes);
    animateNumber('stat-pulls', report.total_pulls);
    animateNumber('stat-users', report.unique_users);

    renderTypeChart(report.events_by_type);
    renderEventFeed(pull.events);
}

function animateNumber(id, target) {
    const el = document.getElementById(id);
    const start = parseInt(el.textContent) || 0;
    const duration = 400;
    const t0 = performance.now();
    function tick(now) {
        const p = Math.min((now - t0) / duration, 1);
        el.textContent = Math.round(start + (target - start) * easeOut(p));
        if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}
function easeOut(t) { return 1 - Math.pow(1 - t, 3); }

function renderTypeChart(byType) {
    const box = document.getElementById('type-chart');
    box.innerHTML = '';
    const entries = Object.entries(byType);
    if (!entries.length) return;

    const w = box.clientWidth || 600, h = 80;
    const total = entries.reduce((s, d) => s + d[1], 0);

    const svg = d3.select(box).append('svg').attr('width', w).attr('height', h);
    let x = 0;
    entries.forEach(([type, count]) => {
        const barW = (count / total) * (w - 8 * entries.length);
        const g = svg.append('g').attr('transform', `translate(${x}, 0)`);
        g.append('rect')
            .attr('y', 20).attr('width', barW).attr('height', 36)
            .attr('rx', 6).attr('fill', C[type] || C.change).attr('opacity', 0.2);
        g.append('rect')
            .attr('y', 20).attr('width', 0).attr('height', 36)
            .attr('rx', 6).attr('fill', C[type] || C.change).attr('opacity', 0.7)
            .transition().duration(600).delay(200).attr('width', barW);
        g.append('text')
            .attr('x', barW / 2).attr('y', 14)
            .attr('text-anchor', 'middle')
            .attr('fill', C[type] || '#8b949e')
            .attr('font-size', '10px').attr('font-weight', '500')
            .text(`${type} (${count})`);
        x += barW + 8;
    });
}

function renderEventFeed(events) {
    const list = document.getElementById('events-list');
    const badge = document.getElementById('event-count');
    badge.textContent = `${events.length} events`;
    list.innerHTML = '';

    events.forEach((evt, i) => {
        const row = document.createElement('div');
        row.className = 'event-row';
        row.style.setProperty('--i', i);

        const typeAbbr = { correction: 'FIX', decision: 'DEC', discovery: 'NEW', broadcast: 'BCT', change: 'CHG' };
        const urgentTag = evt.priority === 'urgent'
            ? '<span class="event-meta-urgent">urgent</span>' : '';

        row.innerHTML = `
            <div class="event-type-dot event-type-dot--${evt.type}">
                ${typeAbbr[evt.type] || evt.type.substring(0, 3).toUpperCase()}
            </div>
            <div class="event-body">
                <div class="event-result">${esc(evt.result)}</div>
                <div class="event-meta">
                    <span class="event-meta-user">${esc(evt.user)}</span>
                    <span>${new Date(evt.ts).toLocaleString()}</span>
                    ${urgentTag}
                </div>
            </div>
        `;
        list.appendChild(row);
    });
}

// ============================================================
// GRAPH — 3-Column: Agents → Events → Scopes
// ============================================================
async function loadGraphData() {
    const res = await fetch(`${API}/api/report/graph?repo_id=${enc(currentRepo)}`);
    graphData = await res.json();
    // Render only if graph tab is active
    if (document.getElementById('graph').classList.contains('active')) {
        renderGraph(graphData);
    }
}

function renderGraph(data) {
    if (!data) return;
    const svg = d3.select('#graph-svg');
    svg.selectAll('*').remove();
    dismissPopover();

    const container = document.getElementById('graph-container');
    const W = container.clientWidth || 900;
    const H = container.clientHeight || 600;
    svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);

    if (!data.nodes.length) {
        svg.append('text').attr('x', W / 2).attr('y', H / 2)
            .attr('text-anchor', 'middle').attr('fill', '#364152')
            .attr('font-size', '14px')
            .text('No events yet. Push some memory events to see the graph.');
        return;
    }

    const polyScopes = new Set(data.polymorphisms.map(p => p.scope));

    const users  = data.nodes.filter(n => n.type === 'user');
    const events = data.nodes.filter(n => n.type === 'event');
    const scopes = data.nodes.filter(n => n.type === 'scope');

    // Build adjacency
    const userEvts = {}, evtScps = {};
    data.edges.forEach(e => {
        if (e.relation === 'pushed')  (userEvts[e.source] = userEvts[e.source] || []).push(e.target);
        if (e.relation === 'affects') (evtScps[e.source] = evtScps[e.source] || []).push(e.target);
    });

    // --- Layout ---
    const colX = [130, W * 0.40, W * 0.78];
    const PAD_TOP = 60;

    // Users
    const userH = Math.min(90, (H - PAD_TOP * 2) / Math.max(users.length, 1));
    const userStartY = PAD_TOP + (H - PAD_TOP * 2 - (users.length - 1) * userH) / 2;
    users.forEach((u, i) => { u.x = colX[0]; u.y = userStartY + i * userH; });

    // Events: group by user
    users.forEach(u => {
        const eIds = userEvts[u.id] || [];
        const eNodes = eIds.map(id => events.find(e => e.id === id)).filter(Boolean);
        const spacing = Math.min(52, userH * 0.85);
        const sy = u.y - ((eNodes.length - 1) * spacing) / 2;
        eNodes.forEach((e, j) => { e.x = colX[1]; e.y = sy + j * spacing; });
    });
    events.filter(e => e.x == null).forEach((e, i) => { e.x = colX[1]; e.y = PAD_TOP + i * 50; });

    // Scopes: average y from connected events
    scopes.forEach(s => {
        const cIds = data.edges.filter(e => e.relation === 'affects' && e.target === s.id).map(e => e.source);
        const ys = cIds.map(id => { const ev = events.find(e => e.id === id); return ev ? ev.y : H / 2; });
        s.x = colX[2];
        s.y = ys.length ? ys.reduce((a, b) => a + b) / ys.length : H / 2;
    });
    // De-overlap
    scopes.sort((a, b) => a.y - b.y);
    for (let i = 1; i < scopes.length; i++) {
        if (scopes[i].y - scopes[i - 1].y < 48) scopes[i].y = scopes[i - 1].y + 48;
    }

    const g = svg.append('g');

    // Zoom
    svg.call(d3.zoom().scaleExtent([0.3, 3]).on('zoom', e => g.attr('transform', e.transform)));
    svg.on('click', e => { if (e.target === svg.node()) dismissPopover(); });

    // Column headers
    const headers = [
        { x: colX[0], label: 'AGENTS', color: C.user },
        { x: colX[1], label: 'EVENTS', color: C.accent },
        { x: colX[2], label: 'SCOPES', color: C.scope },
    ];
    headers.forEach(h => {
        g.append('text').attr('x', h.x).attr('y', 32)
            .attr('text-anchor', 'middle').attr('fill', h.color)
            .attr('font-size', '10px').attr('font-weight', '600')
            .attr('letter-spacing', '2px').attr('opacity', 0.5)
            .text(h.label);
    });

    // Arrows
    const defs = svg.append('defs');
    const mkArrow = (id, color) => {
        defs.append('marker').attr('id', id).attr('viewBox', '0 0 8 6')
            .attr('refX', 8).attr('refY', 3).attr('markerWidth', 6).attr('markerHeight', 5)
            .attr('orient', 'auto')
            .append('path').attr('d', 'M0,0.5 L7,3 L0,5.5').attr('fill', color);
    };
    mkArrow('a-default', '#1a2332');
    mkArrow('a-poly', C.correction);
    mkArrow('a-push', 'rgba(56,189,248,0.3)');

    // --- Edges ---
    const bezier = (sx, sy, tx, ty) => {
        const cx = (sx + tx) / 2;
        return `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
    };

    const links = g.selectAll('.g-edge')
        .data(data.edges).join('path')
        .attr('class', 'g-edge')
        .attr('fill', 'none')
        .attr('d', d => {
            const s = data.nodes.find(n => n.id === d.source);
            const t = data.nodes.find(n => n.id === d.target);
            return s && t ? bezier(s.x, s.y, t.x, t.y) : '';
        })
        .attr('stroke', d => {
            if (polyScopes.has(d.target)) return C.correction;
            if (d.relation === 'pushed') return 'rgba(56,189,248,0.25)';
            return '#1a2332';
        })
        .attr('stroke-width', d => polyScopes.has(d.target) ? 2 : 1.2)
        .attr('stroke-dasharray', d => d.relation === 'pulled' ? '4,3' : '')
        .attr('marker-end', d => {
            if (polyScopes.has(d.target)) return 'url(#a-poly)';
            if (d.relation === 'pushed') return 'url(#a-push)';
            return 'url(#a-default)';
        })
        .attr('opacity', 0)
        .transition().duration(500).delay((d, i) => 100 + i * 30).attr('opacity', 1);

    // --- User nodes ---
    const uG = g.selectAll('.g-user')
        .data(users).join('g')
        .attr('class', 'g-user').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('opacity', 0);
    uG.transition().duration(400).delay((d, i) => i * 60).attr('opacity', 1);

    uG.append('circle').attr('r', 22)
        .attr('fill', 'rgba(56,189,248,0.08)')
        .attr('stroke', 'rgba(56,189,248,0.3)').attr('stroke-width', 1.5);
    uG.append('circle').attr('r', 4).attr('fill', C.user);
    uG.append('text').attr('dy', 38).attr('text-anchor', 'middle')
        .attr('fill', C.user).attr('font-size', '11px').attr('font-weight', '600')
        .text(d => (d.label || d.id).replace('user:', ''));

    // --- Event nodes ---
    const eW = 200, eH = 40;
    const eG = g.selectAll('.g-event')
        .data(events).join('g')
        .attr('class', 'g-event').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('opacity', 0);
    eG.transition().duration(400).delay((d, i) => 200 + i * 40).attr('opacity', 1);

    eG.append('rect')
        .attr('width', eW).attr('height', eH).attr('x', -eW / 2).attr('y', -eH / 2)
        .attr('rx', 8)
        .attr('fill', d => (C[d.event_type] || C.change) + '12')
        .attr('stroke', d => (C[d.event_type] || C.change) + '40')
        .attr('stroke-width', 1);

    // Type badge
    eG.append('rect')
        .attr('x', -eW / 2 + 6).attr('y', -eH / 2 + 5)
        .attr('width', d => (d.event_type || 'evt').length * 6 + 10).attr('height', 14)
        .attr('rx', 4)
        .attr('fill', d => C[d.event_type] || C.change);
    eG.append('text')
        .attr('x', -eW / 2 + 11).attr('y', -eH / 2 + 14)
        .attr('fill', '#06080c').attr('font-size', '8px').attr('font-weight', '700')
        .attr('letter-spacing', '0.5px')
        .text(d => (d.event_type || 'event').toUpperCase());

    // Result
    eG.append('text')
        .attr('x', -eW / 2 + 8).attr('y', eH / 2 - 8)
        .attr('fill', '#c8d6e5').attr('font-size', '10px')
        .text(d => {
            const t = d.label || d.id;
            return t.length > 30 ? t.substring(0, 30) + '...' : t;
        });

    // --- Scope nodes ---
    const sG = g.selectAll('.g-scope')
        .data(scopes).join('g')
        .attr('class', 'g-scope').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('opacity', 0);
    sG.transition().duration(400).delay((d, i) => 400 + i * 50).attr('opacity', 1);

    const sW = 140, sH = 32;
    sG.append('rect')
        .attr('width', sW).attr('height', sH).attr('x', -sW / 2).attr('y', -sH / 2)
        .attr('rx', sH / 2)
        .attr('fill', d => polyScopes.has(d.id) ? 'rgba(255,71,87,0.1)' : 'rgba(90,106,126,0.08)')
        .attr('stroke', d => polyScopes.has(d.id) ? C.correction : '#1a2332')
        .attr('stroke-width', d => polyScopes.has(d.id) ? 1.5 : 1);

    sG.append('text').attr('text-anchor', 'middle').attr('dy', 4)
        .attr('fill', d => polyScopes.has(d.id) ? C.correction : '#5a6a7e')
        .attr('font-size', '10px')
        .attr('font-weight', d => polyScopes.has(d.id) ? '600' : '400')
        .text(d => (d.label || d.id).replace('scope:', ''));

    // Poly warning
    sG.filter(d => polyScopes.has(d.id))
        .append('text').attr('x', sW / 2 - 8).attr('y', -sH / 2 - 4)
        .attr('fill', C.correction).attr('font-size', '12px').text('\u26A0');

    // --- Click: highlight subgraph + popover ---
    const allNodes = g.selectAll('.g-user, .g-event, .g-scope');
    allNodes.on('click', (ev, d) => {
        ev.stopPropagation();
        const conn = new Set([d.id]);
        data.edges.forEach(e => {
            if (e.source === d.id || e.target === d.id) { conn.add(e.source); conn.add(e.target); }
        });
        allNodes.transition().duration(200).attr('opacity', n => conn.has(n.id) ? 1 : 0.1);
        g.selectAll('.g-edge').transition().duration(200)
            .attr('opacity', e => (e.source === d.id || e.target === d.id) ? 1 : 0.04);

        showPopover(d, ev, data);
    });

    // --- Legend ---
    const lg = svg.append('g').attr('transform', `translate(20, ${H - 36})`);
    const items = [
        { c: C.user, l: 'Agent' }, { c: C.correction, l: 'Correction' },
        { c: C.decision, l: 'Decision' }, { c: C.discovery, l: 'Discovery' },
        { c: C.broadcast, l: 'Broadcast' },
    ];
    items.forEach((it, i) => {
        const x = i * 96;
        lg.append('circle').attr('cx', x + 5).attr('cy', 0).attr('r', 4).attr('fill', it.c);
        lg.append('text').attr('x', x + 14).attr('y', 4)
            .attr('fill', '#364152').attr('font-size', '10px').text(it.l);
    });
}

// ============================================================
// TIMELINE — Swimlane
// ============================================================
async function loadTimelineData() {
    const res = await fetch(`${API}/api/report/timeline?repo_id=${enc(currentRepo)}`);
    timelineData = await res.json();
    if (document.getElementById('timeline').classList.contains('active')) {
        renderTimeline(timelineData);
    }
}

function renderTimeline(data) {
    if (!data) return;
    const svg = d3.select('#timeline-svg');
    svg.selectAll('*').remove();
    dismissPopover();

    const users = Object.keys(data.swimlanes);
    if (!users.length) return;

    const laneH = 72;
    const margin = { top: 48, right: 40, bottom: 44, left: 110 };
    const ctr = document.getElementById('timeline-container');
    const W = Math.max(800, ctr.clientWidth || 900);
    const H = margin.top + users.length * laneH + margin.bottom;
    svg.attr('viewBox', `0 0 ${W} ${H}`).attr('width', W).attr('height', H);

    const allEvts = users.flatMap(u => data.swimlanes[u]);
    if (!allEvts.length) return;

    const ext = d3.extent(allEvts, d => new Date(d.ts));
    // Add padding to time extent
    const pad = (ext[1] - ext[0]) * 0.08 || 3600000;
    const x = d3.scaleTime()
        .domain([new Date(ext[0] - pad), new Date(+ext[1] + pad)])
        .range([margin.left, W - margin.right]);
    const y = d3.scaleBand().domain(users).range([margin.top, H - margin.bottom]).padding(0.15);

    // Swimlane bg
    svg.selectAll('.lane-bg')
        .data(users).join('rect')
        .attr('x', 0).attr('width', W)
        .attr('y', d => y(d)).attr('height', y.bandwidth())
        .attr('fill', (d, i) => i % 2 ? 'rgba(17,24,34,0.4)' : 'transparent')
        .attr('rx', 0);

    // Swimlane labels
    svg.selectAll('.lane-label')
        .data(users).join('text')
        .attr('x', 16).attr('y', d => y(d) + y.bandwidth() / 2 + 4)
        .attr('fill', C.user).attr('font-size', '12px').attr('font-weight', '600')
        .text(d => d);

    // Grid lines
    const ticks = x.ticks(8);
    svg.selectAll('.grid-line')
        .data(ticks).join('line')
        .attr('x1', d => x(d)).attr('x2', d => x(d))
        .attr('y1', margin.top).attr('y2', H - margin.bottom)
        .attr('stroke', '#111822').attr('stroke-width', 1);

    // Broadcast lines
    allEvts.filter(e => e.type === 'broadcast').forEach(evt => {
        const bx = x(new Date(evt.ts));
        svg.append('line')
            .attr('x1', bx).attr('x2', bx)
            .attr('y1', margin.top).attr('y2', H - margin.bottom)
            .attr('stroke', C.broadcast).attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '6,4').attr('opacity', 0.5);
        svg.append('text')
            .attr('x', bx + 6).attr('y', margin.top - 6)
            .attr('fill', C.broadcast).attr('font-size', '9px')
            .text('BROADCAST');
    });

    // Events
    users.forEach(user => {
        const evts = data.swimlanes[user];
        const dots = svg.selectAll(`.dot-${user.replace(/\W/g, '_')}`)
            .data(evts).join('g')
            .attr('class', 'tl-dot')
            .attr('cursor', 'pointer')
            .attr('transform', d => `translate(${x(new Date(d.ts))},${y(user) + y.bandwidth() / 2})`);

        // Outer ring
        dots.append('circle').attr('r', 14)
            .attr('fill', d => (C[d.type] || C.change) + '15')
            .attr('stroke', d => (C[d.type] || C.change) + '30')
            .attr('stroke-width', 1);
        // Inner dot
        dots.append('circle').attr('r', 5)
            .attr('fill', d => C[d.type] || C.change);
        // Label
        dots.append('text')
            .attr('dy', 26).attr('text-anchor', 'middle')
            .attr('fill', '#5a6a7e').attr('font-size', '9px')
            .text(d => d.result.substring(0, 18) + (d.result.length > 18 ? '..' : ''));

        // Click
        dots.on('click', (ev, d) => {
            ev.stopPropagation();
            showPopover({
                type: 'event', label: d.result, event_type: d.type,
                data: { result: d.result, process: d.process, ts: d.ts },
            }, ev, null);
        });
    });

    // X axis
    svg.append('g')
        .attr('transform', `translate(0,${H - margin.bottom})`)
        .call(d3.axisBottom(x).ticks(8).tickSize(0).tickPadding(10))
        .call(g => g.select('.domain').attr('stroke', '#1a2332'))
        .selectAll('text').attr('fill', '#364152').attr('font-size', '10px');
}

// ============================================================
// POPOVER
// ============================================================
function showPopover(d, event, graphData) {
    dismissPopover();
    const pop = document.getElementById('graph-popover');
    pop.classList.remove('hidden');

    const name = (d.label || d.id || '').replace(/^(user|event|scope):/, '');
    let html = `<div class="popover-header">${(d.type || '').toUpperCase()}: ${esc(name)}</div>`;

    if (d.type === 'event' && d.data) {
        if (d.data.result) html += `<div class="popover-row"><b>Result:</b> ${esc(d.data.result)}</div>`;
        if (d.data.process && d.data.process.length) {
            html += `<div class="popover-row"><b>Process:</b></div>`;
            d.data.process.forEach(p => { html += `<div class="popover-step">&rarr; ${esc(p)}</div>`; });
        }
        if (d.data.ts) html += `<div class="popover-row muted">${new Date(d.data.ts).toLocaleString()}</div>`;
    } else if (d.type === 'scope' && graphData) {
        const scopeLabel = (d.label || d.id || '').replace('scope:', '');
        const poly = graphData.polymorphisms.find(p => p.scope === scopeLabel || p.scope === d.id);
        if (poly) {
            html += `<div class="popover-row popover-warn">POLYMORPHISM DETECTED</div>`;
            html += `<div class="popover-row">Agents: ${poly.users.join(', ')}</div>`;
            poly.intents.forEach(i => { html += `<div class="popover-step">&bull; ${esc(i)}</div>`; });
        }
    } else if (d.type === 'user') {
        html += `<div class="popover-row">Agent node</div>`;
    }

    pop.innerHTML = html;

    // Position
    const vw = window.innerWidth, vh = window.innerHeight;
    let left = event.clientX + 16;
    let top = event.clientY - 10;
    const pw = 340;
    if (left + pw > vw - 16) left = event.clientX - pw - 16;
    if (top + 200 > vh) top = vh - 220;
    if (top < 8) top = 8;
    pop.style.left = left + 'px';
    pop.style.top = top + 'px';
}

function dismissPopover() {
    const pop = document.getElementById('graph-popover');
    if (pop) pop.classList.add('hidden');
    // Reset all opacities
    d3.selectAll('.g-user, .g-event, .g-scope').transition().duration(200).attr('opacity', 1);
    d3.selectAll('.g-edge').transition().duration(200).attr('opacity', 1);
}

// Dismiss on click outside
document.addEventListener('click', e => {
    const pop = document.getElementById('graph-popover');
    if (pop && !pop.contains(e.target)) dismissPopover();
});

// ============================================================
// UTILS
// ============================================================
function enc(s) { return encodeURIComponent(s); }
function esc(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}
