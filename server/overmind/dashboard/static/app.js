// server/overmind/dashboard/static/app.js

const API_BASE = window.location.origin;
let currentRepo = '';

// --- Tab switching ---
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(btn.dataset.tab).classList.add('active');
        // Re-render graph/timeline when tab becomes visible (needs correct dimensions)
        if (currentRepo) {
            if (btn.dataset.tab === 'graph') loadGraph();
            if (btn.dataset.tab === 'timeline') loadTimeline();
        }
    });
});

function closeDetail() {
    dismissPopover();
}

// --- Repo list loading ---
async function loadRepos() {
    const res = await fetch(`${API_BASE}/api/repos`);
    const repos = await res.json();
    const select = document.getElementById('repo-id');
    // Keep the default option
    select.innerHTML = '<option value="">-- select repo --</option>';
    for (const repo of repos) {
        const opt = document.createElement('option');
        opt.value = repo;
        opt.textContent = repo;
        select.appendChild(opt);
    }
    // Auto-select if only one repo
    if (repos.length === 1) {
        select.value = repos[0];
        loadAll();
    }
}

// Load repos on page load
loadRepos();

// --- Data loading ---
async function loadAll() {
    currentRepo = document.getElementById('repo-id').value.trim();
    if (!currentRepo) return;
    await Promise.all([loadOverview(), loadGraph(), loadTimeline()]);
}

async function loadOverview() {
    const [reportRes, pullRes] = await Promise.all([
        fetch(`${API_BASE}/api/report?repo_id=${encodeURIComponent(currentRepo)}`),
        fetch(`${API_BASE}/api/memory/pull?repo_id=${encodeURIComponent(currentRepo)}&limit=20`),
    ]);
    const report = await reportRes.json();
    const pull = await pullRes.json();

    document.getElementById('stat-pushes').textContent = report.total_pushes;
    document.getElementById('stat-pulls').textContent = report.total_pulls;
    document.getElementById('stat-users').textContent = report.unique_users;

    // Type chart
    renderTypeChart(report.events_by_type);

    // Recent events table
    const tbody = document.querySelector('#events-table tbody');
    tbody.innerHTML = '';
    for (const evt of pull.events) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${new Date(evt.ts).toLocaleString()}</td>
            <td>${evt.user}</td>
            <td><span class="type-badge type-${evt.type}">${evt.type}</span></td>
            <td>${evt.result}</td>
        `;
        tbody.appendChild(tr);
    }
}

function renderTypeChart(byType) {
    const container = document.getElementById('type-chart');
    container.innerHTML = '';
    const entries = Object.entries(byType);
    if (entries.length === 0) return;

    const width = 500, height = 200, margin = { top: 20, right: 20, bottom: 40, left: 50 };
    const svg = d3.select(container).append('svg').attr('width', width).attr('height', height);

    const x = d3.scaleBand()
        .domain(entries.map(d => d[0]))
        .range([margin.left, width - margin.right])
        .padding(0.3);

    const y = d3.scaleLinear()
        .domain([0, d3.max(entries, d => d[1])])
        .nice()
        .range([height - margin.bottom, margin.top]);

    const colorMap = {
        correction: '#f85149', decision: '#d29922', discovery: '#a371f7',
        change: '#3fb950', broadcast: '#f778ba',
    };

    svg.selectAll('rect')
        .data(entries)
        .join('rect')
        .attr('x', d => x(d[0]))
        .attr('y', d => y(d[1]))
        .attr('width', x.bandwidth())
        .attr('height', d => y(0) - y(d[1]))
        .attr('fill', d => colorMap[d[0]] || '#8b949e')
        .attr('rx', 3);

    svg.append('g')
        .attr('transform', `translate(0,${height - margin.bottom})`)
        .call(d3.axisBottom(x))
        .selectAll('text').attr('fill', '#8b949e');

    svg.append('g')
        .attr('transform', `translate(${margin.left},0)`)
        .call(d3.axisLeft(y).ticks(5))
        .selectAll('text').attr('fill', '#8b949e');

    svg.selectAll('.domain, .tick line').attr('stroke', '#30363d');
}

// --- Graph ---
async function loadGraph() {
    const res = await fetch(`${API_BASE}/api/report/graph?repo_id=${encodeURIComponent(currentRepo)}`);
    const data = await res.json();
    renderGraph(data);
}

function renderGraph(data) {
    const svg = d3.select('#graph-svg');
    svg.selectAll('*').remove();
    d3.select('#graph-popover').remove();

    const container = document.getElementById('graph-container');
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 600;
    svg.attr('width', width).attr('height', height)
       .attr('viewBox', `0 0 ${width} ${height}`);

    if (data.nodes.length === 0) {
        svg.append('text').attr('x', width / 2).attr('y', height / 2)
            .attr('text-anchor', 'middle').attr('fill', '#8b949e')
            .text('No data. Push some events first.');
        return;
    }

    const polyScopes = new Set(data.polymorphisms.map(p => p.scope));

    // --- Classify nodes into 3 columns ---
    const users = data.nodes.filter(n => n.type === 'user');
    const events = data.nodes.filter(n => n.type === 'event');
    const scopes = data.nodes.filter(n => n.type === 'scope');

    // Build lookup: which user pushed which events, which events affect which scopes
    const userEvents = {};  // userId -> [eventIds]
    const eventScopes = {}; // eventId -> [scopeIds]
    data.edges.forEach(e => {
        if (e.relation === 'pushed') {
            (userEvents[e.source] = userEvents[e.source] || []).push(e.target);
        }
        if (e.relation === 'affects') {
            (eventScopes[e.source] = eventScopes[e.source] || []).push(e.target);
        }
    });

    // --- 3-column layout: Users | Events | Scopes ---
    const colX = [140, width * 0.42, width * 0.78];
    const legendW = 180; // space for legend on the left

    // Position users vertically, evenly spaced
    const userSpacing = Math.min(80, (height - 80) / Math.max(users.length, 1));
    const userStartY = (height - (users.length - 1) * userSpacing) / 2;
    users.forEach((u, i) => { u.x = colX[0]; u.y = userStartY + i * userSpacing; });

    // Position events: group by user, vertically aligned with their user
    const eventPositions = {};
    let globalEventIndex = 0;
    users.forEach(u => {
        const evtIds = userEvents[u.id] || [];
        const evtNodes = evtIds.map(id => events.find(e => e.id === id)).filter(Boolean);
        const spacing = Math.min(55, (userSpacing * 0.9));
        const startY = u.y - ((evtNodes.length - 1) * spacing) / 2;
        evtNodes.forEach((evt, j) => {
            evt.x = colX[1];
            evt.y = startY + j * spacing;
            eventPositions[evt.id] = { x: evt.x, y: evt.y };
        });
    });
    // Events not attached to any user (shouldn't happen, but safety)
    events.filter(e => e.x === undefined).forEach((e, i) => {
        e.x = colX[1]; e.y = 40 + i * 50;
    });

    // Position scopes: collect y positions from connected events, average them
    const scopeYs = {};
    scopes.forEach(s => {
        const connectedEventIds = data.edges
            .filter(e => e.relation === 'affects' && e.target === s.id)
            .map(e => e.source);
        const ys = connectedEventIds.map(id => {
            const evt = events.find(e => e.id === id);
            return evt ? evt.y : height / 2;
        });
        s.x = colX[2];
        s.y = ys.length > 0 ? ys.reduce((a, b) => a + b) / ys.length : height / 2;
    });
    // De-overlap scopes
    scopes.sort((a, b) => a.y - b.y);
    for (let i = 1; i < scopes.length; i++) {
        if (scopes[i].y - scopes[i - 1].y < 50) {
            scopes[i].y = scopes[i - 1].y + 50;
        }
    }

    // --- Column headers ---
    svg.append('text').attr('x', colX[0]).attr('y', 24).attr('text-anchor', 'middle')
       .attr('fill', '#484f58').attr('font-size', '12px').attr('font-weight', '600').text('AGENTS');
    svg.append('text').attr('x', colX[1]).attr('y', 24).attr('text-anchor', 'middle')
       .attr('fill', '#484f58').attr('font-size', '12px').attr('font-weight', '600').text('EVENTS');
    svg.append('text').attr('x', colX[2]).attr('y', 24).attr('text-anchor', 'middle')
       .attr('fill', '#484f58').attr('font-size', '12px').attr('font-weight', '600').text('SCOPES');

    const g = svg.append('g');

    // Zoom
    svg.call(d3.zoom().scaleExtent([0.3, 3]).on('zoom', (e) => {
        g.attr('transform', e.transform);
    }));
    svg.on('click', (e) => { if (e.target === svg.node()) dismissPopover(); });

    // --- Arrow marker ---
    const defs = svg.append('defs');
    defs.append('marker').attr('id', 'arr').attr('viewBox', '0 0 10 6')
        .attr('refX', 10).attr('refY', 3).attr('markerWidth', 7).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,0 L10,3 L0,6').attr('fill', '#484f58');
    defs.append('marker').attr('id', 'arr-poly').attr('viewBox', '0 0 10 6')
        .attr('refX', 10).attr('refY', 3).attr('markerWidth', 7).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,0 L10,3 L0,6').attr('fill', '#f85149');

    // --- Draw edges as curves ---
    const linkGen = (sx, sy, tx, ty) => {
        const mx = (sx + tx) / 2;
        return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`;
    };

    const link = g.selectAll('.edge-path')
        .data(data.edges)
        .join('path')
        .attr('fill', 'none')
        .attr('stroke-width', d => {
            const tid = d.target;
            return polyScopes.has(tid) ? 2.5 : 1.5;
        })
        .attr('stroke', d => {
            const tid = d.target;
            if (polyScopes.has(tid)) return '#f85149';
            if (d.relation === 'pulled') return '#58a6ff';
            return '#30363d';
        })
        .attr('stroke-dasharray', d => d.relation === 'pulled' ? '6,4' : '')
        .attr('marker-end', d => {
            const tid = d.target;
            return polyScopes.has(tid) ? 'url(#arr-poly)' : 'url(#arr)';
        })
        .attr('d', d => {
            const sn = data.nodes.find(n => n.id === d.source);
            const tn = data.nodes.find(n => n.id === d.target);
            if (!sn || !tn) return '';
            return linkGen(sn.x, sn.y, tn.x, tn.y);
        });

    // Edge labels
    g.selectAll('.edge-label')
        .data(data.edges)
        .join('text')
        .attr('class', 'edge-label')
        .attr('text-anchor', 'middle')
        .attr('fill', '#3d444d')
        .attr('font-size', '9px')
        .attr('x', d => {
            const sn = data.nodes.find(n => n.id === d.source);
            const tn = data.nodes.find(n => n.id === d.target);
            return sn && tn ? (sn.x + tn.x) / 2 : 0;
        })
        .attr('y', d => {
            const sn = data.nodes.find(n => n.id === d.source);
            const tn = data.nodes.find(n => n.id === d.target);
            return sn && tn ? (sn.y + tn.y) / 2 - 6 : 0;
        })
        .text(d => d.relation);

    // --- Draw nodes ---
    const colorMap = {
        correction: '#f85149', decision: '#d29922', discovery: '#a371f7',
        change: '#3fb950', broadcast: '#f778ba',
    };

    // User nodes
    const userG = g.selectAll('.user-node')
        .data(users).join('g')
        .attr('class', 'node').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`);
    userG.append('circle').attr('r', 18).attr('fill', '#58a6ff').attr('opacity', 0.15)
         .attr('stroke', '#58a6ff').attr('stroke-width', 2);
    userG.append('text').attr('text-anchor', 'middle').attr('dy', 5)
         .attr('fill', '#58a6ff').attr('font-size', '12px').attr('font-weight', '600')
         .text(d => (d.label || d.id).replace('user:', ''));

    // Event nodes
    const evtG = g.selectAll('.event-node')
        .data(events).join('g')
        .attr('class', 'node').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`);
    evtG.append('rect')
        .attr('width', 180).attr('height', 36).attr('x', -90).attr('y', -18)
        .attr('rx', 6)
        .attr('fill', d => {
            const c = colorMap[d.event_type] || '#3fb950';
            return c + '22';  // low opacity fill
        })
        .attr('stroke', d => colorMap[d.event_type] || '#3fb950')
        .attr('stroke-width', 1.5);
    // Type badge
    evtG.append('rect')
        .attr('width', d => d.event_type ? d.event_type.length * 6.5 + 8 : 40)
        .attr('height', 14).attr('x', -87).attr('y', -14).attr('rx', 3)
        .attr('fill', d => colorMap[d.event_type] || '#3fb950');
    evtG.append('text').attr('x', -83).attr('y', -4)
        .attr('fill', '#fff').attr('font-size', '9px').attr('font-weight', '600')
        .text(d => d.event_type || 'event');
    // Result text
    evtG.append('text').attr('x', -83).attr('y', 12)
        .attr('fill', '#c9d1d9').attr('font-size', '10px')
        .text(d => {
            const label = d.label || d.id;
            return label.length > 28 ? label.substring(0, 28) + '...' : label;
        });

    // Scope nodes
    const scopeG = g.selectAll('.scope-node')
        .data(scopes).join('g')
        .attr('class', 'node').attr('cursor', 'pointer')
        .attr('transform', d => `translate(${d.x},${d.y})`);
    scopeG.append('rect')
        .attr('width', 120).attr('height', 30).attr('x', -60).attr('y', -15)
        .attr('rx', 15)
        .attr('fill', d => polyScopes.has(d.id) ? '#f8514922' : '#161b22')
        .attr('stroke', d => polyScopes.has(d.id) ? '#f85149' : '#30363d')
        .attr('stroke-width', d => polyScopes.has(d.id) ? 2 : 1);
    scopeG.append('text').attr('text-anchor', 'middle').attr('dy', 4)
        .attr('fill', d => polyScopes.has(d.id) ? '#f85149' : '#8b949e')
        .attr('font-size', '11px').attr('font-weight', d => polyScopes.has(d.id) ? '600' : '400')
        .text(d => (d.label || d.id).replace('scope:', ''));
    // Polymorphism warning icon
    scopes.filter(s => polyScopes.has(s.id)).forEach(s => {
        const sg = scopeG.filter(d => d.id === s.id);
        sg.append('text').attr('x', 48).attr('y', -8)
           .attr('fill', '#f85149').attr('font-size', '14px').text('\u26A0');
    });

    // --- Click handler: popover + focus ---
    const allNodeGroups = g.selectAll('.node');
    allNodeGroups.on('click', (e, d) => {
        e.stopPropagation();

        // Highlight connected
        const connectedIds = new Set([d.id]);
        data.edges.forEach(edge => {
            if (edge.source === d.id || edge.target === d.id) {
                connectedIds.add(edge.source);
                connectedIds.add(edge.target);
            }
        });

        allNodeGroups.attr('opacity', n => connectedIds.has(n.id) ? 1 : 0.15);
        link.attr('opacity', edge => (edge.source === d.id || edge.target === d.id) ? 1 : 0.08);

        showPopover(d, e, data);
    });

    // --- Legend (bottom-left) ---
    const legend = svg.append('g').attr('transform', `translate(16, ${height - 100})`);
    const items = [
        { color: '#58a6ff', label: 'Agent' },
        { color: '#f85149', label: 'Correction' },
        { color: '#d29922', label: 'Decision' },
        { color: '#a371f7', label: 'Discovery' },
        { color: '#f778ba', label: 'Broadcast' },
    ];
    items.forEach((item, i) => {
        const x = i * 100;
        legend.append('rect').attr('x', x).attr('y', 0).attr('width', 10).attr('height', 10)
              .attr('rx', item.color === '#58a6ff' ? 5 : 2).attr('fill', item.color);
        legend.append('text').attr('x', x + 14).attr('y', 9)
              .attr('fill', '#8b949e').attr('font-size', '10px').text(item.label);
    });
    legend.append('line').attr('x1', 0).attr('y1', 22).attr('x2', 20).attr('y2', 22)
          .attr('stroke', '#f85149').attr('stroke-width', 2);
    legend.append('text').attr('x', 24).attr('y', 26)
          .attr('fill', '#8b949e').attr('font-size', '10px').text('= polymorphism conflict');

    function showPopover(d, event, graphData) {
        dismissPopover();
        const popover = document.createElement('div');
        popover.id = 'graph-popover';

        const name = (d.label || d.id).replace(/^(user|event|scope):/, '');
        let html = `<div class="popover-header">${d.type.toUpperCase()}: ${name}</div>`;

        if (d.type === 'event' && d.data) {
            if (d.data.result) html += `<div class="popover-row"><b>Result:</b> ${d.data.result}</div>`;
            if (d.data.process && d.data.process.length) {
                html += `<div class="popover-row"><b>Process:</b></div>`;
                d.data.process.forEach(p => { html += `<div class="popover-step">&rarr; ${p}</div>`; });
            }
            if (d.data.ts) html += `<div class="popover-row muted">${new Date(d.data.ts).toLocaleString()}</div>`;
        } else if (d.type === 'user') {
            const evtCount = (userEvents[d.id] || []).length;
            html += `<div class="popover-row">Pushed ${evtCount} event(s)</div>`;
        } else if (d.type === 'scope') {
            const poly = graphData.polymorphisms.find(p => p.scope === (d.label || d.id));
            if (!poly) {
                // Also try with scope: prefix stripped
                const scopeLabel = (d.label || d.id).replace('scope:', '');
                const poly2 = graphData.polymorphisms.find(p => p.scope === scopeLabel);
                if (poly2) {
                    html += `<div class="popover-row popover-warn">Polymorphism detected!</div>`;
                    html += `<div class="popover-row">Users: ${poly2.users.join(', ')}</div>`;
                    poly2.intents.forEach(i => { html += `<div class="popover-step">&bull; ${i}</div>`; });
                }
            } else {
                html += `<div class="popover-row popover-warn">Polymorphism detected!</div>`;
                html += `<div class="popover-row">Users: ${poly.users.join(', ')}</div>`;
                poly.intents.forEach(i => { html += `<div class="popover-step">&bull; ${i}</div>`; });
            }
        }

        popover.innerHTML = html;
        container.appendChild(popover);

        const rect = container.getBoundingClientRect();
        let left = event.clientX - rect.left + 16;
        let top = event.clientY - rect.top - 10;
        const pw = 320, ph = popover.offsetHeight || 200;
        if (left + pw > rect.width) left = left - pw - 32;
        if (top + ph > rect.height) top = rect.height - ph - 8;
        if (top < 0) top = 8;
        popover.style.left = left + 'px';
        popover.style.top = top + 'px';
    }
}

function dismissPopover() {
    const existing = document.getElementById('graph-popover');
    if (existing) existing.remove();
    // Reset opacity
    d3.selectAll('.node').attr('opacity', 1);
    d3.selectAll('.edge').attr('opacity', 1);
}

// --- Timeline ---
async function loadTimeline() {
    const res = await fetch(`${API_BASE}/api/report/timeline?repo_id=${encodeURIComponent(currentRepo)}`);
    const data = await res.json();
    renderTimeline(data);
}

function renderTimeline(data) {
    const svg = d3.select('#timeline-svg');
    svg.selectAll('*').remove();

    const users = Object.keys(data.swimlanes);
    if (users.length === 0) return;

    const laneHeight = 80;
    const margin = { top: 40, right: 40, bottom: 40, left: 120 };
    const width = Math.max(800, document.getElementById('timeline-container').clientWidth || 900);
    const height = margin.top + users.length * laneHeight + margin.bottom;
    svg.attr('viewBox', `0 0 ${width} ${height}`);

    // Collect all timestamps
    const allEvents = users.flatMap(u => data.swimlanes[u]);
    if (allEvents.length === 0) return;

    const extent = d3.extent(allEvents, d => new Date(d.ts));
    const x = d3.scaleTime().domain(extent).range([margin.left, width - margin.right]).nice();
    const y = d3.scaleBand().domain(users).range([margin.top, height - margin.bottom]).padding(0.2);

    // Swimlane backgrounds
    svg.selectAll('.swimlane-bg')
        .data(users)
        .join('rect')
        .attr('class', 'swimlane-bg')
        .attr('x', 0).attr('width', width)
        .attr('y', d => y(d)).attr('height', y.bandwidth())
        .attr('fill', (d, i) => i % 2 === 0 ? '#161b22' : '#0d1117');

    // Swimlane labels
    svg.selectAll('.swimlane-label')
        .data(users)
        .join('text')
        .attr('class', 'swimlane-label')
        .attr('x', 12)
        .attr('y', d => y(d) + y.bandwidth() / 2 + 5)
        .text(d => d);

    const colorMap = {
        correction: '#f85149', decision: '#d29922', discovery: '#a371f7',
        change: '#3fb950', broadcast: '#f778ba',
    };

    // Events
    for (const user of users) {
        const events = data.swimlanes[user];
        svg.selectAll(`.evt-${user.replace(/\W/g, '_')}`)
            .data(events)
            .join('circle')
            .attr('class', 'timeline-event')
            .attr('cx', d => x(new Date(d.ts)))
            .attr('cy', y(user) + y.bandwidth() / 2)
            .attr('r', 6)
            .attr('fill', d => colorMap[d.type] || '#8b949e')
            .on('click', (e, d) => {
                const panel = document.getElementById('detail-panel');
                panel.classList.remove('hidden');
                document.getElementById('detail-content').textContent = JSON.stringify(d, null, 2);
            });

        // Broadcast vertical lines
        events.filter(e => e.type === 'broadcast').forEach(evt => {
            svg.append('line')
                .attr('class', 'timeline-broadcast-line')
                .attr('x1', x(new Date(evt.ts))).attr('x2', x(new Date(evt.ts)))
                .attr('y1', margin.top).attr('y2', height - margin.bottom);
        });
    }

    // X axis
    svg.append('g')
        .attr('transform', `translate(0,${height - margin.bottom})`)
        .call(d3.axisBottom(x).ticks(8))
        .selectAll('text').attr('fill', '#8b949e');

    svg.selectAll('.domain, .tick line').attr('stroke', '#30363d');
}
