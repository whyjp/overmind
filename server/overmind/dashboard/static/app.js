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
    // Remove any leftover popover
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
    const relationLabels = { pushed: 'pushed', affects: 'affects', pulled: 'pulled' };

    // --- Simulation: stabilize then stop ---
    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(120).strength(0.8))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(40))
        .alphaDecay(0.05);  // faster cooldown

    const g = svg.append('g');

    // Zoom
    const zoom = d3.zoom().scaleExtent([0.1, 4]).on('zoom', (e) => {
        g.attr('transform', e.transform);
    });
    svg.call(zoom);
    // Click on background dismisses popover
    svg.on('click', (e) => {
        if (e.target === svg.node()) dismissPopover();
    });

    // --- Legend ---
    const legend = svg.append('g').attr('transform', 'translate(16, 16)');
    const legendItems = [
        { shape: 'circle', color: '#58a6ff', label: 'User / Agent' },
        { shape: 'rect', color: '#f85149', label: 'Correction' },
        { shape: 'rect', color: '#d29922', label: 'Decision' },
        { shape: 'rect', color: '#a371f7', label: 'Discovery' },
        { shape: 'rect', color: '#f778ba', label: 'Broadcast' },
        { shape: 'diamond', color: '#8b949e', label: 'Scope (file area)' },
    ];
    legendItems.forEach((item, i) => {
        const row = legend.append('g').attr('transform', `translate(0, ${i * 22})`);
        if (item.shape === 'circle') {
            row.append('circle').attr('cx', 7).attr('cy', 7).attr('r', 6).attr('fill', item.color);
        } else if (item.shape === 'diamond') {
            row.append('rect').attr('x', 2).attr('y', 2).attr('width', 10).attr('height', 10)
               .attr('fill', item.color).attr('rx', 2).attr('transform', 'rotate(45, 7, 7)');
        } else {
            row.append('rect').attr('x', 1).attr('y', 1).attr('width', 12).attr('height', 12)
               .attr('fill', item.color).attr('rx', 2);
        }
        row.append('text').attr('x', 22).attr('y', 11).attr('fill', '#8b949e')
           .attr('font-size', '11px').text(item.label);
    });
    // Edge legend
    const edgeLegY = legendItems.length * 22 + 8;
    const edgeLegend = [
        { dash: '', color: '#58a6ff', label: 'pushed / affects' },
        { dash: '5,5', color: '#8b949e', label: 'pulled' },
        { dash: '', color: '#f85149', label: 'polymorphism conflict' },
    ];
    edgeLegend.forEach((item, i) => {
        const row = legend.append('g').attr('transform', `translate(0, ${edgeLegY + i * 20})`);
        row.append('line').attr('x1', 0).attr('y1', 8).attr('x2', 16).attr('y2', 8)
           .attr('stroke', item.color).attr('stroke-width', 2)
           .attr('stroke-dasharray', item.dash);
        row.append('text').attr('x', 22).attr('y', 12).attr('fill', '#8b949e')
           .attr('font-size', '11px').text(item.label);
    });

    // --- Edges with arrow markers ---
    svg.append('defs').append('marker')
        .attr('id', 'arrowhead').attr('viewBox', '0 0 10 6')
        .attr('refX', 10).attr('refY', 3).attr('markerWidth', 8).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,0 L10,3 L0,6').attr('fill', '#484f58');

    const link = g.selectAll('.edge')
        .data(data.edges)
        .join('line')
        .attr('marker-end', 'url(#arrowhead)')
        .attr('class', d => {
            let cls = 'edge';
            if (d.relation === 'pulled') cls += ' edge-pulled';
            const tid = typeof d.target === 'object' ? d.target.id : d.target;
            if (polyScopes.has(tid)) cls += ' edge-polymorphism';
            return cls;
        });

    // Edge labels
    const edgeLabel = g.selectAll('.edge-label')
        .data(data.edges)
        .join('text')
        .attr('class', 'edge-label')
        .attr('text-anchor', 'middle')
        .attr('fill', '#484f58')
        .attr('font-size', '9px')
        .text(d => relationLabels[d.relation] || '');

    // --- Nodes ---
    const nodeSize = d => d.type === 'user' ? 16 : d.type === 'scope' ? 12 : 10;
    const nodeClass = d => {
        if (d.type === 'user') return 'node-user';
        if (d.type === 'scope') return 'node-scope' + (polyScopes.has(d.id) ? ' polymorphism-glow' : '');
        return `node-event node-event-${d.event_type || 'change'}`;
    };

    const node = g.selectAll('.node')
        .data(data.nodes)
        .join('g')
        .attr('class', d => 'node' + (d.type === 'user' ? ' node-group-user' : ''))
        .attr('cursor', 'pointer')
        .call(d3.drag()
            .on('start', (e, d) => {
                if (!e.active) simulation.alphaTarget(0.1).restart();
                d.fx = d.x; d.fy = d.y;
            })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => {
                if (!e.active) simulation.alphaTarget(0);
                // Pin the dragged node in place
                d.fx = d.x; d.fy = d.y;
            })
        );

    node.each(function(d) {
        const el = d3.select(this);
        if (d.type === 'user') {
            el.append('circle').attr('r', nodeSize(d)).attr('class', nodeClass(d));
        } else if (d.type === 'scope') {
            // Diamond shape for scope
            const s = nodeSize(d);
            el.append('rect')
                .attr('width', s * 1.6).attr('height', s * 1.6)
                .attr('x', -s * 0.8).attr('y', -s * 0.8)
                .attr('rx', 3)
                .attr('class', nodeClass(d))
                .attr('transform', 'rotate(45)');
        } else {
            const s = nodeSize(d);
            el.append('rect')
                .attr('width', s * 2).attr('height', s * 2)
                .attr('x', -s).attr('y', -s)
                .attr('rx', 3)
                .attr('class', nodeClass(d));
        }
    });

    // Labels
    node.append('text')
        .attr('class', 'node-label')
        .attr('dy', d => nodeSize(d) + 16)
        .attr('text-anchor', 'middle')
        .text(d => {
            if (d.type === 'user') return d.label || d.id;
            if (d.type === 'scope') return d.label || d.id;
            // For events, show short result
            return (d.label || d.id).substring(0, 25);
        });

    // --- Click: floating popover near node ---
    let selectedNode = null;
    node.on('click', (e, d) => {
        e.stopPropagation();
        selectedNode = d;

        // Highlight connected edges
        link.attr('opacity', edge => {
            const sid = typeof edge.source === 'object' ? edge.source.id : edge.source;
            const tid = typeof edge.target === 'object' ? edge.target.id : edge.target;
            return (sid === d.id || tid === d.id) ? 1 : 0.15;
        });
        node.attr('opacity', n => {
            if (n.id === d.id) return 1;
            // Check if connected
            const connected = data.edges.some(edge => {
                const sid = typeof edge.source === 'object' ? edge.source.id : edge.source;
                const tid = typeof edge.target === 'object' ? edge.target.id : edge.target;
                return (sid === d.id && tid === n.id) || (tid === d.id && sid === n.id);
            });
            return connected ? 1 : 0.2;
        });

        showPopover(d, e);
    });

    // --- Simulation tick ---
    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        edgeLabel
            .attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2 - 4);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Stop simulation after layout stabilizes
    simulation.on('end', () => {
        // Fix all nodes in place after stabilization
        data.nodes.forEach(d => { d.fx = d.x; d.fy = d.y; });
    });

    // --- Popover functions ---
    function showPopover(d, event) {
        dismissPopover();
        const popover = document.createElement('div');
        popover.id = 'graph-popover';

        let html = `<div class="popover-header">${d.type.toUpperCase()}: ${(d.label || d.id)}</div>`;

        if (d.type === 'event' && d.data) {
            if (d.data.result) html += `<div class="popover-row"><b>Result:</b> ${d.data.result}</div>`;
            if (d.data.process && d.data.process.length) {
                html += `<div class="popover-row"><b>Process:</b></div>`;
                d.data.process.forEach(p => { html += `<div class="popover-step">&rarr; ${p}</div>`; });
            }
            if (d.data.ts) html += `<div class="popover-row muted">${new Date(d.data.ts).toLocaleString()}</div>`;
        } else if (d.type === 'scope') {
            const poly = data.polymorphisms.find(p => p.scope === d.id);
            if (poly) {
                html += `<div class="popover-row popover-warn">Polymorphism detected!</div>`;
                html += `<div class="popover-row">Users: ${poly.users.join(', ')}</div>`;
                poly.intents.forEach(i => { html += `<div class="popover-step">&bull; ${i}</div>`; });
            }
        }

        popover.innerHTML = html;
        container.appendChild(popover);

        // Position near mouse, within bounds
        const rect = container.getBoundingClientRect();
        let left = event.clientX - rect.left + 16;
        let top = event.clientY - rect.top - 10;
        // Keep within container
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
