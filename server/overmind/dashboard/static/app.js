/* =========================================================
   OVERMIND DASHBOARD — app.js
   ========================================================= */

const API = window.location.origin;
let currentRepo = '';
let graphData = null;
let flowData = null;
let timelineData = null;
let graphViewMode = 'flow'; // 'flow', 'agent', or 'scope'
let activeScope = null; // currently selected scope filter
let activeAgent = null; // currently selected agent filter (flow view)
let flowTimeZoomK = 1;    // flow view time axis zoom level
let flowTimePanOffset = 0; // flow view time axis pan offset

// --- Auto-refresh (SSE) ---
let autoRefreshSource = null;  // EventSource for SSE

function getActiveTab() {
    const active = document.querySelector('.tab.active');
    return active ? active.dataset.tab : 'overview';
}

async function refreshActiveTab() {
    // Refresh repo list first — may discover new repos
    await refreshRepoList();

    if (!currentRepo) return;

    // Visual feedback: spin the refresh button
    const btn = document.getElementById('refresh-btn');
    if (btn) btn.classList.add('spinning');

    try {
        const tab = getActiveTab();
        if (tab === 'overview') await loadOverview();
        else if (tab === 'graph') { await loadGraphData(); await loadFlowData(); }
        else if (tab === 'timeline') await loadTimelineData();
    } catch (e) {
        console.warn('Refresh failed:', e);
    }

    if (btn) setTimeout(() => btn.classList.remove('spinning'), 300);
}

async function refreshRepoList() {
    try {
        const res = await fetch(`${API}/api/repos`);
        const repos = await res.json();
        const sel = document.getElementById('repo-id');
        const current = sel.value;
        const existing = new Set([...sel.options].map(o => o.value));
        let newRepos = [];
        repos.forEach(r => {
            if (!existing.has(r)) {
                const o = document.createElement('option');
                o.value = r; o.textContent = r;
                sel.appendChild(o);
                newRepos.push(r);
            }
        });
        // Auto-select: if no repo selected, pick first available
        if (!current && repos.length > 0) {
            sel.value = repos[0];
            loadAll();
        }
        // If a new repo appeared and nothing was selected, switch to it
        else if (newRepos.length > 0 && !current) {
            sel.value = newRepos[0];
            loadAll();
        }
    } catch (e) { /* server may be restarting */ }
}

function toggleAutoRefresh() {
    const btn = document.getElementById('auto-refresh-btn');
    const label = document.getElementById('auto-refresh-label');

    if (autoRefreshSource) {
        // SSE active → disconnect
        autoRefreshSource.close();
        autoRefreshSource = null;
        btn.classList.remove('active');
        label.textContent = 'AUTO';
        return;
    }

    // Need a repo to subscribe
    if (!currentRepo) {
        refreshRepoList().then(() => {
            if (currentRepo) toggleAutoRefresh();  // retry after repo selected
        });
        return;
    }

    // Open SSE connection — with repo_id if selected, global otherwise
    const params = currentRepo ? `repo_id=${enc(currentRepo)}` : '';
    const url = `${API}/api/stream${params ? '?' + params : ''}`;
    autoRefreshSource = new EventSource(url);

    autoRefreshSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'update') {
                refreshActiveTab();
            } else if (data.type === 'repos') {
                // New repo discovered — update dropdown
                const sel = document.getElementById('repo-id');
                const existing = new Set([...sel.options].map(o => o.value));
                (data.new || []).forEach(r => {
                    if (!existing.has(r)) {
                        const o = document.createElement('option');
                        o.value = r; o.textContent = r;
                        sel.appendChild(o);
                    }
                });
                // Auto-select if nothing selected
                if (!sel.value && data.all && data.all.length > 0) {
                    sel.value = data.all[0];
                    loadAll();
                }
            }
            // 'connected' type — just confirms stream is alive
        } catch (e) {
            console.warn('SSE parse error:', e);
        }
    };

    autoRefreshSource.onerror = () => {
        console.warn('SSE connection error — will auto-reconnect');
    };

    btn.classList.add('active');
    label.textContent = 'LIVE';
    if (currentRepo) refreshActiveTab();
}

// Reconnect SSE when repo changes
function reconnectSSE() {
    if (autoRefreshSource) {
        autoRefreshSource.close();
        autoRefreshSource = null;
        // Re-open with new repo
        toggleAutoRefresh();
    }
}

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

// --- View toggle ---
document.querySelectorAll('.view-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        graphViewMode = btn.dataset.view;
        activeScope = null;
        activeAgent = null;
        flowTimeZoomK = 1;
        flowTimePanOffset = 0;
        renderGraph(graphData);
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
    reconnectSSE();  // reconnect SSE to new repo if active
    await Promise.all([loadOverview(), loadGraphData(), loadFlowData(), loadTimelineData()]);
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

async function loadFlowData() {
    const res = await fetch(`${API}/api/report/flow?repo_id=${enc(currentRepo)}`);
    flowData = await res.json();
}

function renderGraph(data) {
    if (!data) return;
    if (graphViewMode === 'flow') return renderFlowView(flowData || data);
    if (graphViewMode === 'scope') return renderGraphScopeView(data);
    renderGraphAgentView(data);
}

function renderScopeFilterPanel(data, scopes, polyScopes) {
    const filterPanel = document.getElementById('graph-scope-filter');
    filterPanel.innerHTML = '';

    if (!scopes.length) return;

    const label = document.createElement('span');
    label.className = 'scope-label';
    label.textContent = 'Scope:';
    filterPanel.appendChild(label);

    // "All" button
    const allBtn = document.createElement('button');
    allBtn.className = 'scope-btn' + (activeScope === null ? ' active' : '');
    allBtn.textContent = 'All';
    allBtn.addEventListener('click', () => {
        activeScope = null;
        renderGraph(data);
    });
    filterPanel.appendChild(allBtn);

    scopes.forEach(s => {
        const scopeLabel = (s.label || s.id).replace('scope:', '');
        if (scopeLabel === '*') return;
        const btn = document.createElement('button');
        const isPoly = polyScopes.has(s.id) || polyScopes.has(scopeLabel);
        btn.className = 'scope-btn' + (isPoly ? ' poly' : '') + (activeScope === s.id ? ' active' : '');
        btn.textContent = scopeLabel;
        btn.addEventListener('click', () => {
            activeScope = activeScope === s.id ? null : s.id;
            renderGraph(data);
        });
        filterPanel.appendChild(btn);
    });
}

function buildScopeConnectedSet(data, scopeId) {
    // Find all nodes connected to this scope
    const conn = new Set([scopeId]);
    // Events that affect this scope
    data.edges.forEach(e => {
        if (e.relation === 'affects' && e.target === scopeId) {
            conn.add(e.source); // event
            // Find user who pushed this event
            data.edges.forEach(e2 => {
                if (e2.target === e.source && e2.relation === 'pushed') conn.add(e2.source);
                // Ghost edges from this event
                if (e2.source === e.source && e2.relation === 'pulled') {
                    conn.add(e2.target); // ghost
                    // Find consumer of ghost
                    data.edges.forEach(e3 => {
                        if (e3.target === e2.target && e3.relation === 'consumed') conn.add(e3.source);
                    });
                }
            });
        }
    });
    return conn;
}

// ============================================================
// FLOW VIEW — 3-axis: X=time, Y=agents, Z=push/pull
// ============================================================
function renderFlowView(data) {
    const svg = d3.select('#graph-svg');
    svg.selectAll('*').remove();
    dismissPopover();

    const filterPanel = document.getElementById('graph-scope-filter');
    filterPanel.innerHTML = '';

    const container = document.getElementById('graph-container');
    const W = container.clientWidth || 900;
    const H = container.clientHeight || 600;

    if (!data || !data.events || !data.events.length) {
        svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);
        svg.append('text').attr('x', W / 2).attr('y', H / 2)
            .attr('text-anchor', 'middle').attr('fill', '#364152').attr('font-size', '14px')
            .text('No flow data. Run crosstest to generate push-pull cycles.');
        return;
    }

    const agents = data.agents || [];
    const events = data.events || [];
    const pullLinks = data.pull_links || [];

    // Agent filter panel
    const agentLabel = document.createElement('span');
    agentLabel.className = 'scope-label';
    agentLabel.textContent = 'Agent:';
    filterPanel.appendChild(agentLabel);

    const allBtn = document.createElement('button');
    allBtn.className = 'scope-btn' + (activeAgent === null ? ' active' : '');
    allBtn.textContent = 'All';
    allBtn.addEventListener('click', () => { activeAgent = null; renderGraph(graphData); });
    filterPanel.appendChild(allBtn);

    agents.forEach(a => {
        const btn = document.createElement('button');
        btn.className = 'scope-btn' + (activeAgent === a ? ' active' : '');
        btn.textContent = a;
        btn.addEventListener('click', () => {
            activeAgent = activeAgent === a ? null : a;
            renderGraph(graphData);
        });
        filterPanel.appendChild(btn);
    });

    // Layout — one row per agent, push events as dots, pull = cross-agent edges
    const margin = { top: 56, right: 40, bottom: 44, left: 120 };
    const laneH = Math.max(60, Math.min(100, (H - margin.top - margin.bottom) / agents.length));
    const totalH = Math.max(H, margin.top + agents.length * laneH + margin.bottom);
    const dotR = 8;

    svg.attr('width', W).attr('height', totalH).attr('viewBox', `0 0 ${W} ${totalH}`);

    // Time scale — domain stored for Ctrl+Wheel zoom
    const timeExtent = d3.extent(events, d => new Date(d.ts));
    const timePad = (timeExtent[1] - timeExtent[0]) * 0.08 || 3600000;
    const baseTimeDomain = [new Date(timeExtent[0] - timePad), new Date(+timeExtent[1] + timePad)];
    const xRange = [margin.left + 20, W - margin.right - 20];
    const xScale = d3.scaleTime().domain(baseTimeDomain).range(xRange);

    function getZoomedXScale() {
        const mid = (+baseTimeDomain[0] + +baseTimeDomain[1]) / 2;
        const halfSpan = (+baseTimeDomain[1] - +baseTimeDomain[0]) / 2 / flowTimeZoomK;
        const offset = flowTimePanOffset * (+baseTimeDomain[1] - +baseTimeDomain[0]) / 2;
        return d3.scaleTime()
            .domain([new Date(mid - halfSpan + offset), new Date(mid + halfSpan + offset)])
            .range(xRange);
    }

    // Agent Y scale
    const yScale = d3.scaleBand()
        .domain(agents)
        .range([margin.top, margin.top + agents.length * laneH])
        .padding(0.2);

    const g = svg.append('g');

    // --- Zoom ---
    // Drag = pan both axes (uniform transform on g)
    // Ctrl+Wheel = zoom time axis only (re-renders node positions)
    const uniformZoom = d3.zoom()
        .scaleExtent([0.3, 4])
        .filter(event => !event.ctrlKey) // skip Ctrl events
        .on('zoom', e => g.attr('transform', e.transform));
    svg.call(uniformZoom);

    // Ctrl+Wheel: zoom time axis, re-layout nodes
    svg.on('wheel', (event) => {
        if (!event.ctrlKey) return;
        event.preventDefault();
        event.stopPropagation();

        const factor = event.deltaY > 0 ? 0.85 : 1.15;
        flowTimeZoomK = Math.max(0.5, Math.min(30, flowTimeZoomK * factor));

        // Re-render with new time zoom (debounced via requestAnimationFrame)
        requestAnimationFrame(() => renderFlowView(data));
    }, { passive: false });

    // Shift+Wheel: pan time axis
    svg.on('wheel.timepan', (event) => {
        if (!event.shiftKey || event.ctrlKey) return;
        event.preventDefault();
        const panStep = 0.05 / flowTimeZoomK;
        flowTimePanOffset += event.deltaY > 0 ? panStep : -panStep;
        requestAnimationFrame(() => renderFlowView(data));
    }, { passive: false });

    // Ctrl+0: reset time zoom
    svg.on('keydown', (event) => {
        if (event.ctrlKey && event.key === '0') {
            event.preventDefault();
            flowTimeZoomK = 1;
            flowTimePanOffset = 0;
            renderFlowView(data);
        }
    });
    // Make SVG focusable for keyboard events
    svg.attr('tabindex', 0);

    // Apply current time zoom
    const zoomedX = flowTimeZoomK !== 1 || flowTimePanOffset !== 0 ? getZoomedXScale() : xScale;

    // Compute SVG width needed — expand if zoomed in
    const effectiveW = Math.max(W, (W - margin.left - margin.right) * flowTimeZoomK + margin.left + margin.right);
    svg.attr('width', effectiveW).attr('height', totalH).attr('viewBox', `0 0 ${effectiveW} ${totalH}`);

    // Update xScale range for expanded width
    if (flowTimeZoomK > 1) {
        zoomedX.range([margin.left + 20, effectiveW - margin.right - 20]);
    }

    svg.on('click', e => { if (e.target === svg.node()) dismissPopover(); });

    // Time zoom indicator
    if (flowTimeZoomK !== 1) {
        svg.append('text')
            .attr('x', effectiveW - 10).attr('y', 16)
            .attr('text-anchor', 'end')
            .attr('fill', C.accent).attr('font-size', '10px').attr('opacity', 0.6)
            .text(`Time: ${flowTimeZoomK.toFixed(1)}x  (Ctrl+Wheel: zoom, Shift+Wheel: pan, Ctrl+0: reset)`);
    }

    // Defs
    const defs = svg.append('defs');
    defs.append('marker').attr('id', 'a-flow-pull').attr('viewBox', '0 0 8 6')
        .attr('refX', 8).attr('refY', 3).attr('markerWidth', 5).attr('markerHeight', 4)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,0.5 L7,3 L0,5.5').attr('fill', 'rgba(0,229,160,0.8)');

    // Swimlane backgrounds + labels
    agents.forEach((agent, i) => {
        g.append('rect')
            .attr('x', margin.left).attr('width', W - margin.left - margin.right)
            .attr('y', yScale(agent)).attr('height', yScale.bandwidth())
            .attr('rx', 4)
            .attr('fill', i % 2 ? 'rgba(17,24,34,0.25)' : 'transparent');
        g.append('text')
            .attr('x', 12).attr('y', yScale(agent) + yScale.bandwidth() / 2 + 4)
            .attr('fill', C.user).attr('font-size', '11px').attr('font-weight', '600')
            .text(agent);
    });

    // Grid lines
    zoomedX.ticks(Math.max(8, Math.round(8 * flowTimeZoomK))).forEach(tick => {
        g.append('line')
            .attr('x1', zoomedX(tick)).attr('x2', zoomedX(tick))
            .attr('y1', margin.top).attr('y2', margin.top + agents.length * laneH)
            .attr('stroke', '#0d1520').attr('stroke-width', 1);
    });

    // Time axis
    const axisG = g.append('g')
        .attr('transform', `translate(0,${margin.top + agents.length * laneH + 4})`)
        .call(d3.axisBottom(zoomedX).ticks(Math.max(8, Math.round(8 * flowTimeZoomK))).tickSize(0).tickPadding(8));
    axisG.select('.domain').attr('stroke', '#1a2332');
    axisG.selectAll('text').attr('fill', '#364152').attr('font-size', '10px');

    // Event positions
    const evtPos = {};
    events.forEach(evt => {
        evtPos[evt.id] = {
            x: zoomedX(new Date(evt.ts)),
            y: yScale(evt.user) + yScale.bandwidth() / 2,
        };
    });

    // Build per-agent sorted event list (for finding "next push after pull")
    const agentEvents = {};
    events.forEach(evt => {
        (agentEvents[evt.user] = agentEvents[evt.user] || []).push(evt);
    });

    // Pull count map
    const pullCountMap = {};
    pullLinks.forEach(l => {
        if (!pullCountMap[l.event_id]) pullCountMap[l.event_id] = new Set();
        pullCountMap[l.event_id].add(l.puller);
    });

    // --- Pull edges: source push event → puller's NEXT push event ---
    // This shows information flow: "I pulled your event, then I pushed mine"
    const flowEdges = [];
    const edgeSeen = new Set();
    pullLinks.forEach(link => {
        const srcPos = evtPos[link.event_id];
        if (!srcPos) return;
        const srcEvt = events.find(e => e.id === link.event_id);
        if (!srcEvt) return;

        // Find puller's next push event after the PULL timestamp (not source event time).
        // This ensures we don't connect to events the puller already pushed before pulling.
        const pullerEvts = agentEvents[link.puller] || [];
        const pullTime = link.ts ? new Date(link.ts) : new Date(srcEvt.ts);
        const nextEvt = pullerEvts.find(e => new Date(e.ts) > pullTime);

        const tgtId = nextEvt ? nextEvt.id : null;
        const key = `${link.event_id}→${tgtId || link.puller}`;
        if (edgeSeen.has(key)) return;
        edgeSeen.add(key);

        if (nextEvt && evtPos[nextEvt.id]) {
            flowEdges.push({
                sx: srcPos.x, sy: srcPos.y,
                tx: evtPos[nextEvt.id].x, ty: evtPos[nextEvt.id].y,
                srcId: link.event_id, tgtId: nextEvt.id, puller: link.puller,
            });
        } else {
            // No next push — draw to puller's lane at right edge
            const ty = yScale(link.puller) + yScale.bandwidth() / 2;
            flowEdges.push({
                sx: srcPos.x, sy: srcPos.y,
                tx: srcPos.x + 30, ty,
                srcId: link.event_id, tgtId: null, puller: link.puller,
            });
        }
    });

    // Agent filter: compute connected event set
    let agentConn = null; // set of event IDs relevant to activeAgent
    let agentEdgeSet = null; // set of edge keys relevant to activeAgent
    if (activeAgent) {
        agentConn = new Set();
        agentEdgeSet = new Set();
        // Agent's own push events
        events.filter(e => e.user === activeAgent).forEach(e => agentConn.add(e.id));
        // Edges where agent is the pusher (source event belongs to agent) or puller
        flowEdges.forEach((fe, i) => {
            const srcEvt = events.find(e => e.id === fe.srcId);
            const tgtEvt = fe.tgtId ? events.find(e => e.id === fe.tgtId) : null;
            const srcIsAgent = srcEvt && srcEvt.user === activeAgent;
            const tgtIsAgent = tgtEvt && tgtEvt.user === activeAgent;
            const pullerIsAgent = fe.puller === activeAgent;
            if (srcIsAgent || tgtIsAgent || pullerIsAgent) {
                agentEdgeSet.add(i);
                agentConn.add(fe.srcId);
                if (fe.tgtId) agentConn.add(fe.tgtId);
            }
        });
    }
    const evtDimmed = id => agentConn && !agentConn.has(id);
    const edgeDimmed = i => agentEdgeSet && !agentEdgeSet.has(i);

    // Draw edges
    flowEdges.forEach((d, i) => {
        const midX = (d.sx + d.tx) / 2;
        g.append('path')
            .attr('d', `M${d.sx},${d.sy} C${midX},${d.sy} ${midX},${d.ty} ${d.tx},${d.ty}`)
            .attr('fill', 'none')
            .attr('stroke', edgeDimmed(i) ? 'rgba(0,229,160,0.06)' : 'rgba(0,229,160,0.35)')
            .attr('stroke-width', edgeDimmed(i) ? 0.8 : 1.5)
            .attr('stroke-dasharray', '5,3')
            .attr('marker-end', edgeDimmed(i) ? '' : 'url(#a-flow-pull)')
            .attr('class', 'flow-edge')
            .attr('data-src', d.srcId)
            .attr('data-tgt', d.tgtId || '');
    });

    // --- Ghost dots: transparent replica at puller's row showing "received here" ---
    // For each pull edge, place a faint copy of the source event dot at the
    // source event's x position but on the puller's y row.
    const ghostSeen = new Set();
    flowEdges.forEach((d, i) => {
        const srcEvt = events.find(e => e.id === d.srcId);
        if (!srcEvt) return;
        const ghostKey = `${d.srcId}@${d.puller}`;
        if (ghostSeen.has(ghostKey)) return;
        ghostSeen.add(ghostKey);

        const gx = evtPos[d.srcId].x;
        const gy = yScale(d.puller) + yScale.bandwidth() / 2;
        const dim = edgeDimmed(i);

        const ghost = g.append('g')
            .attr('class', 'flow-ghost')
            .attr('transform', `translate(${gx},${gy})`)
            .attr('opacity', dim ? 0.03 : 0.12);

        // Ghost outer ring (same type color, very faint)
        ghost.append('circle')
            .attr('r', dotR + 2)
            .attr('fill', 'none')
            .attr('stroke', C[srcEvt.type] || C.change)
            .attr('stroke-width', 1)
            .attr('stroke-dasharray', '3,2');

        // Ghost inner dot
        ghost.append('circle')
            .attr('r', dotR - 2)
            .attr('fill', C[srcEvt.type] || C.change)
            .attr('opacity', 0.4);
    });

    // --- Event dots (solid push events) ---
    const evtGroups = g.selectAll('.flow-evt')
        .data(events).join('g')
        .attr('class', 'flow-evt')
        .attr('cursor', 'pointer')
        .attr('transform', d => `translate(${evtPos[d.id].x},${evtPos[d.id].y})`)
        .attr('opacity', d => evtDimmed(d.id) ? 0.12 : 1);

    // Outer glow
    evtGroups.append('circle')
        .attr('r', dotR + 4)
        .attr('fill', d => (C[d.type] || C.change) + '08')
        .attr('stroke', d => (C[d.type] || C.change) + '20')
        .attr('stroke-width', 0.5);
    // Main dot
    evtGroups.append('circle')
        .attr('r', dotR)
        .attr('fill', d => C[d.type] || C.change)
        .attr('opacity', 0.85);
    // Center highlight
    evtGroups.append('circle')
        .attr('r', 2.5)
        .attr('fill', '#fff')
        .attr('opacity', 0.6);

    // Pull count badge
    evtGroups.filter(d => pullCountMap[d.id]?.size).append('text')
        .attr('x', 0).attr('y', -dotR - 6)
        .attr('text-anchor', 'middle')
        .attr('fill', C.accent).attr('font-size', '8px').attr('font-weight', '700')
        .text(d => pullCountMap[d.id].size + '\u2193');

    // --- Interactions ---
    evtGroups.on('mouseenter', (ev, d) => {
        showPopover({
            type: 'event', label: d.result, event_type: d.type,
            data: { result: d.result, process: d.process, ts: d.ts,
                    pulled_by: pullCountMap[d.id] ? Array.from(pullCountMap[d.id]).join(', ') : null },
        }, ev, null);
    });

    evtGroups.on('click', (ev, d) => {
        ev.stopPropagation();
        // Find all connected events (pulled from this, or this pulled from)
        const conn = new Set([d.id]);
        flowEdges.forEach(e => {
            if (e.srcId === d.id && e.tgtId) conn.add(e.tgtId);
            if (e.tgtId === d.id) conn.add(e.srcId);
        });
        evtGroups.transition().duration(200).attr('opacity', n => conn.has(n.id) ? 1 : 0.1);
        g.selectAll('.flow-edge').transition().duration(200)
            .attr('opacity', function() {
                const el = d3.select(this);
                return el.attr('data-src') === d.id || el.attr('data-tgt') === d.id ? 1 : 0.04;
            });
    });

    // --- Agent HEAD labels: last push & last pull per agent ---
    // Collect last pull (ghost) per agent: latest pull_link timestamp per puller
    const lastPullPerAgent = {};
    pullLinks.forEach(link => {
        const prev = lastPullPerAgent[link.puller];
        if (!prev || link.ts > prev.ts) {
            lastPullPerAgent[link.puller] = link;
        }
    });

    agents.forEach(agent => {
        const agentEvts = agentEvents[agent] || [];
        const laneY = yScale(agent) + yScale.bandwidth() / 2;

        // Last PUSH: rightmost event on this agent's lane
        if (agentEvts.length > 0) {
            const lastPush = agentEvts[agentEvts.length - 1];
            const pos = evtPos[lastPush.id];
            if (pos) {
                const labelG = g.append('g')
                    .attr('transform', `translate(${pos.x + dotR + 6},${pos.y})`);
                labelG.append('rect')
                    .attr('x', 0).attr('y', -8).attr('width', 62).attr('height', 16)
                    .attr('rx', 3)
                    .attr('fill', (C[lastPush.type] || C.change) + '20')
                    .attr('stroke', (C[lastPush.type] || C.change) + '40')
                    .attr('stroke-width', 0.5);
                labelG.append('text')
                    .attr('x', 5).attr('y', 3)
                    .attr('fill', C[lastPush.type] || C.change)
                    .attr('font-size', '8px').attr('font-weight', '600')
                    .attr('letter-spacing', '0.5px')
                    .text('LAST PUSH');
            }
        }

        // Last PULL: find the ghost position for this agent's latest pull
        const lastPull = lastPullPerAgent[agent];
        if (lastPull && evtPos[lastPull.event_id]) {
            const srcPos = evtPos[lastPull.event_id];
            const gx = srcPos.x;  // ghost X = original event X
            const gy = laneY;     // ghost Y = puller's lane

            const labelG = g.append('g')
                .attr('transform', `translate(${gx + dotR + 6},${gy})`);
            labelG.append('rect')
                .attr('x', 0).attr('y', -8).attr('width', 56).attr('height', 16)
                .attr('rx', 3)
                .attr('fill', 'rgba(0,229,160,0.08)')
                .attr('stroke', 'rgba(0,229,160,0.25)')
                .attr('stroke-width', 0.5);
            labelG.append('text')
                .attr('x', 5).attr('y', 3)
                .attr('fill', C.accent)
                .attr('font-size', '8px').attr('font-weight', '600')
                .attr('letter-spacing', '0.5px')
                .text('LAST PULL');
        }

        // Agent status summary at the right edge of the lane
        const rightEdge = effectiveW - margin.right + 4;
        const statusLines = [];
        if (agentEvts.length > 0) {
            const last = agentEvts[agentEvts.length - 1];
            const scope = last.scope || (last.files.length ? last.files[0].replace(/\\/, '/').replace(/\/[^/]+$/, '/*') : '');
            statusLines.push({ text: `\u25B6 ${agentEvts.length} pushed`, color: C[last.type] || C.change });
            if (scope) statusLines.push({ text: scope, color: '#4a5568' });
        }
        const pullCount = pullLinks.filter(l => l.puller === agent).length;
        if (pullCount > 0) {
            statusLines.push({ text: `\u25BC ${pullCount} pulled`, color: C.accent });
        }

        statusLines.forEach((line, i) => {
            g.append('text')
                .attr('x', rightEdge)
                .attr('y', laneY - 8 + i * 12)
                .attr('text-anchor', 'start')
                .attr('fill', line.color)
                .attr('font-size', '9px')
                .attr('font-weight', '500')
                .text(line.text);
        });
    });

    // --- Legend ---
    const lg = svg.append('g').attr('transform', `translate(20, ${totalH - 28})`);
    const typeItems = [
        { c: C.decision, l: 'Decision' }, { c: C.correction, l: 'Correction' },
        { c: C.discovery, l: 'Discovery' }, { c: C.change, l: 'Change' },
        { c: C.broadcast, l: 'Broadcast' },
    ];
    typeItems.forEach((it, i) => {
        const x = i * 90;
        lg.append('circle').attr('cx', x + 4).attr('cy', 0).attr('r', 4).attr('fill', it.c);
        lg.append('text').attr('x', x + 14).attr('y', 3).attr('fill', '#4a5568').attr('font-size', '10px').text(it.l);
    });
    const elX = typeItems.length * 90 + 16;
    lg.append('line').attr('x1', elX).attr('y1', 0).attr('x2', elX + 28).attr('y2', 0)
        .attr('stroke', 'rgba(0,229,160,0.5)').attr('stroke-width', 1.3).attr('stroke-dasharray', '5,3');
    lg.append('text').attr('x', elX + 34).attr('y', 3).attr('fill', '#4a5568').attr('font-size', '10px').text('info flow (pull)');
    lg.append('text').attr('x', elX + 130).attr('y', 3).attr('fill', C.accent).attr('font-size', '10px').text('N\u2193 = pull count');
}

function renderGraphAgentView(data) {
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
    const origEvents = data.nodes.filter(n => n.type === 'event' && !(n.data && n.data.ghost));
    const ghostEvents = data.nodes.filter(n => n.type === 'event' && n.data && n.data.ghost);
    const allEvents = data.nodes.filter(n => n.type === 'event');
    const scopes = data.nodes.filter(n => n.type === 'scope');

    // Render scope filter panel
    renderScopeFilterPanel(data, scopes, polyScopes);

    // Compute scope-connected set for filtering
    const scopeConn = activeScope ? buildScopeConnectedSet(data, activeScope) : null;

    // Reset all node positions (prevent stale coords from previous render)
    data.nodes.forEach(n => { delete n.x; delete n.y; delete n._blockStart; });

    // Build adjacency
    const userEvts = {}, userGhosts = {};
    data.edges.forEach(e => {
        if (e.relation === 'pushed')   (userEvts[e.source] = userEvts[e.source] || []).push(e.target);
        if (e.relation === 'consumed') (userGhosts[e.source] = userGhosts[e.source] || []).push(e.target);
    });

    // --- Layout ---
    const colX = [100, W * 0.48];
    const PAD_TOP = 60;

    const cardH = 64;
    let yOffset = PAD_TOP;
    users.forEach(u => {
        const pushed = (userEvts[u.id] || []).length;
        const ghosts = (userGhosts[u.id] || []).length;
        const totalCards = Math.max(pushed + ghosts, 1);
        const blockH = totalCards * cardH;
        u.x = colX[0];
        u.y = yOffset + blockH / 2;
        u._blockStart = yOffset;
        yOffset += blockH + 24;
    });

    users.forEach(u => {
        const eIds = userEvts[u.id] || [];
        const eNodes = eIds.map(id => origEvents.find(e => e.id === id)).filter(Boolean);
        const gIds = userGhosts[u.id] || [];
        const gNodes = gIds.map(id => ghostEvents.find(e => e.id === id)).filter(Boolean);
        const allCards = [...eNodes, ...gNodes];
        const startY = u._blockStart;
        allCards.forEach((e, j) => {
            e.x = colX[1];
            e.y = startY + j * cardH + cardH / 2;
        });
    });
    allEvents.filter(e => e.x == null).forEach((e, i) => { e.x = colX[1]; e.y = PAD_TOP + i * 50; });

    const g = svg.append('g');
    svg.call(d3.zoom().scaleExtent([0.3, 3]).on('zoom', e => g.attr('transform', e.transform)));
    svg.on('click', e => { if (e.target === svg.node()) dismissPopover(); });

    // Column headers
    const headers = [
        { x: colX[0], label: 'AGENTS', color: C.user },
        { x: colX[1], label: 'EVENTS', color: C.accent },
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
    mkArrow('a-push', 'rgba(56,189,248,0.6)');
    mkArrow('a-pull', 'rgba(0,229,160,0.7)');

    const bezier = (sx, sy, tx, ty) => {
        const cx = (sx + tx) / 2;
        return `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
    };

    const visibleEdges = data.edges.filter(e => e.relation !== 'affects');
    const dimmed = id => scopeConn && !scopeConn.has(id);

    g.selectAll('.g-edge')
        .data(visibleEdges).join('path')
        .attr('class', 'g-edge')
        .attr('fill', 'none')
        .attr('d', d => {
            const s = data.nodes.find(n => n.id === d.source);
            const t = data.nodes.find(n => n.id === d.target);
            return s && t ? bezier(s.x, s.y, t.x, t.y) : '';
        })
        .attr('stroke', d => {
            if (d.relation === 'pulled') return 'rgba(0,229,160,0.7)';
            if (d.relation === 'consumed') return 'rgba(0,229,160,0.5)';
            if (d.relation === 'pushed') return 'rgba(56,189,248,0.5)';
            return '#1a2332';
        })
        .attr('stroke-width', d => {
            if (d.relation === 'pulled') return 2;
            if (d.relation === 'consumed') return 1.8;
            return 1.5;
        })
        .attr('stroke-dasharray', d => (d.relation === 'pulled' || d.relation === 'consumed') ? '6,4' : '')
        .attr('marker-end', d => {
            if (d.relation === 'pulled' || d.relation === 'consumed') return 'url(#a-pull)';
            if (d.relation === 'pushed') return 'url(#a-push)';
            return 'url(#a-default)';
        })
        .attr('opacity', d => (dimmed(d.source) && dimmed(d.target)) ? 0.08 : 1);

    // --- User nodes ---
    const uG = g.selectAll('.g-user')
        .data(users).join('g')
        .attr('class', 'g-user').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('opacity', d => dimmed(d.id) ? 0.12 : 1);

    uG.append('circle').attr('r', 22)
        .attr('fill', 'rgba(56,189,248,0.08)')
        .attr('stroke', 'rgba(56,189,248,0.4)').attr('stroke-width', 1.5);
    uG.append('circle').attr('r', 4).attr('fill', C.user);
    uG.append('text').attr('dy', 38).attr('text-anchor', 'middle')
        .attr('fill', C.user).attr('font-size', '11px').attr('font-weight', '600')
        .text(d => (d.label || d.id).replace('user:', ''));

    // --- Event nodes ---
    const eW = 260, eH = 56;
    const eG = g.selectAll('.g-event')
        .data(allEvents).join('g')
        .attr('class', 'g-event').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`)
        .attr('opacity', d => dimmed(d.id) ? 0.12 : 1);

    const isGhost = d => d.data && d.data.ghost;

    // Card background
    eG.append('rect')
        .attr('width', eW).attr('height', eH).attr('x', -eW / 2).attr('y', -eH / 2)
        .attr('rx', 8)
        .attr('fill', d => isGhost(d) ? 'rgba(0,229,160,0.04)' : (C[d.event_type] || C.change) + '10')
        .attr('stroke', d => isGhost(d) ? 'rgba(0,229,160,0.25)' : (C[d.event_type] || C.change) + '40')
        .attr('stroke-width', d => isGhost(d) ? 1.5 : 1)
        .attr('stroke-dasharray', d => isGhost(d) ? '4,3' : '');

    // Ghost indicator — left accent bar
    eG.filter(d => isGhost(d)).append('rect')
        .attr('x', -eW / 2).attr('y', -eH / 2)
        .attr('width', 3).attr('height', eH)
        .attr('rx', 1)
        .attr('fill', C.accent);

    // Type badge
    eG.append('rect')
        .attr('x', -eW / 2 + 8).attr('y', -eH / 2 + 6)
        .attr('width', d => (d.event_type || 'evt').length * 6 + 12).attr('height', 15)
        .attr('rx', 4)
        .attr('fill', d => C[d.event_type] || C.change);
    eG.append('text')
        .attr('x', -eW / 2 + 14).attr('y', -eH / 2 + 16)
        .attr('fill', '#06080c').attr('font-size', '8px').attr('font-weight', '700')
        .attr('letter-spacing', '0.5px')
        .text(d => (d.event_type || 'event').toUpperCase());

    // Ghost badge — "PULLED" label next to type badge
    eG.filter(d => isGhost(d)).append('rect')
        .attr('x', d => -eW / 2 + 8 + (d.event_type || 'evt').length * 6 + 16)
        .attr('y', -eH / 2 + 6)
        .attr('width', 42).attr('height', 15)
        .attr('rx', 4)
        .attr('fill', 'rgba(0,229,160,0.2)');
    eG.filter(d => isGhost(d)).append('text')
        .attr('x', d => -eW / 2 + 14 + (d.event_type || 'evt').length * 6 + 16)
        .attr('y', -eH / 2 + 16)
        .attr('fill', C.accent).attr('font-size', '8px').attr('font-weight', '600')
        .attr('letter-spacing', '0.5px')
        .text('PULLED');

    // Ghost "from: user" label (top-right)
    eG.filter(d => isGhost(d)).append('text')
        .attr('x', eW / 2 - 8).attr('y', -eH / 2 + 16)
        .attr('text-anchor', 'end')
        .attr('fill', 'rgba(0,229,160,0.6)')
        .attr('font-size', '9px')
        .text(d => `\u2190 ${d.data.original_user}`);

    // Result text (middle row)
    eG.append('text')
        .attr('x', -eW / 2 + 10).attr('y', 4)
        .attr('fill', d => isGhost(d) ? '#6a7a8e' : '#dce6f0')
        .attr('font-size', '11px')
        .text(d => {
            const t = d.label || d.id;
            return t.length > 32 ? t.substring(0, 32) + '...' : t;
        });

    // Scope tags (bottom row, separate from result text)
    const evtScopeLabels = {};
    data.edges.forEach(e => {
        if (e.relation === 'affects') {
            const scopeNode = scopes.find(s => s.id === e.target);
            const label = scopeNode ? (scopeNode.label || scopeNode.id).replace('scope:', '') : '';
            if (label && label !== '*') {
                (evtScopeLabels[e.source] = evtScopeLabels[e.source] || []).push(label);
            }
        }
    });

    eG.each(function(d) {
        const scopeList = evtScopeLabels[d.id] || [];
        if (!scopeList.length) return;
        const el = d3.select(this);
        const isPoly = scopeList.some(s => polyScopes.has(`scope:${s}`) || polyScopes.has(s));
        const tag = scopeList.slice(0, 2).join(', ');
        el.append('text')
            .attr('x', -eW / 2 + 10).attr('y', eH / 2 - 6)
            .attr('fill', isPoly ? C.correction : '#4a5568')
            .attr('font-size', '9px')
            .attr('font-weight', isPoly ? '600' : '400')
            .text((isPoly ? '\u26A0 ' : '\u2192 ') + tag);
    });

    // --- Click: highlight subgraph + popover ---
    const allNodes = g.selectAll('.g-user, .g-event');
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
    renderGraphLegend(svg, H);
}

// ============================================================
// GRAPH — Scope View
// ============================================================
function renderGraphScopeView(data) {
    const svg = d3.select('#graph-svg');
    svg.selectAll('*').remove();
    dismissPopover();

    const container = document.getElementById('graph-container');
    const W = container.clientWidth || 900;
    const H = container.clientHeight || 600;
    svg.attr('width', W).attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);

    const polyScopes = new Set(data.polymorphisms.map(p => p.scope));
    const users = data.nodes.filter(n => n.type === 'user');
    const scopes = data.nodes.filter(n => n.type === 'scope');
    const allEvents = data.nodes.filter(n => n.type === 'event');

    // Render scope filter panel
    renderScopeFilterPanel(data, scopes, polyScopes);

    // Reset all node positions
    data.nodes.forEach(n => { delete n.x; delete n.y; delete n._blockStart; });

    if (!scopes.length) {
        svg.append('text').attr('x', W / 2).attr('y', H / 2)
            .attr('text-anchor', 'middle').attr('fill', '#364152')
            .attr('font-size', '14px')
            .text('No scopes yet. Events need file paths or scope fields.');
        return;
    }

    // Build scope→users and scope→events maps
    const scopeToEvents = {};
    const scopeToUsers = {};
    data.edges.forEach(e => {
        if (e.relation === 'affects') {
            (scopeToEvents[e.target] = scopeToEvents[e.target] || new Set()).add(e.source);
        }
    });
    // event→user map
    const eventToUser = {};
    data.edges.forEach(e => {
        if (e.relation === 'pushed') eventToUser[e.target] = e.source;
    });
    // ghost→consumer map
    const ghostToConsumer = {};
    data.edges.forEach(e => {
        if (e.relation === 'consumed') ghostToConsumer[e.target] = e.source;
    });

    // For each scope, find which users pushed events affecting it, and which consumed
    scopes.forEach(s => {
        const evtIds = scopeToEvents[s.id] || new Set();
        const pushers = new Set();
        const consumers = new Set();
        evtIds.forEach(eid => {
            const pusher = eventToUser[eid];
            if (pusher) pushers.add(pusher);
            const consumer = ghostToConsumer[eid];
            if (consumer) consumers.add(consumer);
        });
        // Also check ghost events that are pulled copies of events in this scope
        data.edges.forEach(e => {
            if (e.relation === 'pulled' && evtIds.has(e.source)) {
                const consumer = ghostToConsumer[e.target];
                if (consumer) consumers.add(consumer);
            }
        });
        scopeToUsers[s.id] = { pushers, consumers };
    });

    // Layout: scopes in center column, users on both sides
    const PAD_TOP = 60;
    const centerX = W / 2;
    const scopeSpacing = Math.min(80, (H - PAD_TOP * 2) / Math.max(scopes.length, 1));

    // Filter scopes if active
    const visibleScopes = activeScope ? scopes.filter(s => s.id === activeScope) : scopes;

    visibleScopes.forEach((s, i) => {
        s.x = centerX;
        s.y = PAD_TOP + i * scopeSpacing + scopeSpacing / 2;
    });

    // Position users around scopes
    const userPositions = {};
    users.forEach((u, i) => {
        // Determine which side based on index (alternate)
        const side = i % 2 === 0 ? -1 : 1;
        const xOffset = side * (W * 0.32);
        u.x = centerX + xOffset;
        u.y = PAD_TOP + i * 70 + 35;
        userPositions[u.id] = { x: u.x, y: u.y };
    });

    const g = svg.append('g');
    svg.call(d3.zoom().scaleExtent([0.3, 3]).on('zoom', e => g.attr('transform', e.transform)));
    svg.on('click', e => { if (e.target === svg.node()) dismissPopover(); });

    // Arrows
    const defs = svg.append('defs');
    const mkArrow = (id, color) => {
        defs.append('marker').attr('id', id).attr('viewBox', '0 0 8 6')
            .attr('refX', 8).attr('refY', 3).attr('markerWidth', 6).attr('markerHeight', 5)
            .attr('orient', 'auto')
            .append('path').attr('d', 'M0,0.5 L7,3 L0,5.5').attr('fill', color);
    };
    mkArrow('a-push-sv', 'rgba(56,189,248,0.4)');
    mkArrow('a-pull-sv', 'rgba(0,229,160,0.5)');

    // Column headers
    g.append('text').attr('x', centerX).attr('y', 28)
        .attr('text-anchor', 'middle').attr('fill', C.scope)
        .attr('font-size', '10px').attr('font-weight', '600')
        .attr('letter-spacing', '2px').attr('opacity', 0.5)
        .text('SCOPES');

    const bezier = (sx, sy, tx, ty) => {
        const cx = (sx + tx) / 2;
        return `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
    };

    // Draw edges: user → scope (push) and scope → user (pull/consumed)
    const edgeData = [];
    visibleScopes.forEach(s => {
        const info = scopeToUsers[s.id] || { pushers: new Set(), consumers: new Set() };
        info.pushers.forEach(uid => {
            const u = users.find(u => u.id === uid);
            if (u) {
                // Count events pushed to this scope by this user
                const evtIds = scopeToEvents[s.id] || new Set();
                let count = 0;
                evtIds.forEach(eid => { if (eventToUser[eid] === uid) count++; });
                edgeData.push({ sx: u.x, sy: u.y, tx: s.x, ty: s.y, type: 'push', count });
            }
        });
        info.consumers.forEach(uid => {
            const u = users.find(u => u.id === uid);
            if (u) edgeData.push({ sx: s.x, sy: s.y, tx: u.x, ty: u.y, type: 'pull', count: 0 });
        });
    });

    g.selectAll('.g-sv-edge')
        .data(edgeData).join('path')
        .attr('class', 'g-sv-edge g-edge')
        .attr('fill', 'none')
        .attr('d', d => bezier(d.sx, d.sy, d.tx, d.ty))
        .attr('stroke', d => d.type === 'push' ? 'rgba(56,189,248,0.3)' : 'rgba(0,229,160,0.3)')
        .attr('stroke-width', d => Math.max(1.5, Math.min(d.count, 4)))
        .attr('stroke-dasharray', d => d.type === 'pull' ? '6,4' : '')
        .attr('marker-end', d => d.type === 'push' ? 'url(#a-push-sv)' : 'url(#a-pull-sv)');

    // --- User nodes ---
    const uG = g.selectAll('.g-user')
        .data(users).join('g')
        .attr('class', 'g-user').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`);

    uG.append('circle').attr('r', 22)
        .attr('fill', 'rgba(56,189,248,0.08)')
        .attr('stroke', 'rgba(56,189,248,0.3)').attr('stroke-width', 1.5);
    uG.append('circle').attr('r', 4).attr('fill', C.user);
    uG.append('text').attr('dy', 38).attr('text-anchor', 'middle')
        .attr('fill', C.user).attr('font-size', '11px').attr('font-weight', '600')
        .text(d => (d.label || d.id).replace('user:', ''));

    // --- Scope nodes ---
    const sR = 28;
    const sG = g.selectAll('.g-scope')
        .data(visibleScopes).join('g')
        .attr('class', 'g-scope').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`);

    sG.append('circle').attr('r', sR)
        .attr('fill', d => polyScopes.has(d.id) || polyScopes.has((d.label || '').replace('scope:', ''))
            ? 'rgba(255,71,87,0.08)' : 'rgba(90,106,126,0.08)')
        .attr('stroke', d => polyScopes.has(d.id) || polyScopes.has((d.label || '').replace('scope:', ''))
            ? 'rgba(255,71,87,0.4)' : 'rgba(90,106,126,0.3)')
        .attr('stroke-width', 1.5);

    sG.append('text').attr('text-anchor', 'middle').attr('dy', 4)
        .attr('fill', d => polyScopes.has(d.id) || polyScopes.has((d.label || '').replace('scope:', ''))
            ? C.correction : '#8b949e')
        .attr('font-size', '9px').attr('font-weight', '500')
        .text(d => {
            const l = (d.label || d.id).replace('scope:', '');
            return l.length > 16 ? l.substring(0, 16) + '..' : l;
        });

    // Event count badge
    sG.append('text').attr('text-anchor', 'middle').attr('dy', -sR - 8)
        .attr('fill', '#5a6a7e').attr('font-size', '9px')
        .text(d => {
            const count = (scopeToEvents[d.id] || new Set()).size;
            return count + ' event' + (count !== 1 ? 's' : '');
        });

    // Click on scope node
    const allNodes = g.selectAll('.g-user, .g-scope');
    allNodes.on('click', (ev, d) => {
        ev.stopPropagation();
        showPopover(d, ev, data);
    });

    // Legend
    renderGraphLegend(svg, H);
}

function renderGraphLegend(svg, H) {
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
    const elX = items.length * 96 + 20;
    lg.append('line').attr('x1', elX).attr('y1', 0).attr('x2', elX + 20).attr('y2', 0)
        .attr('stroke', 'rgba(56,189,248,0.4)').attr('stroke-width', 1.5);
    lg.append('text').attr('x', elX + 26).attr('y', 4)
        .attr('fill', '#364152').attr('font-size', '10px').text('pushed');
    lg.append('line').attr('x1', elX + 90).attr('y1', 0).attr('x2', elX + 110).attr('y2', 0)
        .attr('stroke', 'rgba(0,229,160,0.5)').attr('stroke-width', 1.5).attr('stroke-dasharray', '6,4');
    lg.append('text').attr('x', elX + 116).attr('y', 4)
        .attr('fill', '#364152').attr('font-size', '10px').text('pulled (consumed)');
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
        if (d.data.pulled_by) html += `<div class="popover-row"><b>Pulled by:</b> ${esc(d.data.pulled_by)}</div>`;
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
