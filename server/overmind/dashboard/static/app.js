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
    document.getElementById('detail-panel').classList.add('hidden');
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

    const simulation = d3.forceSimulation(data.nodes)
        .force('link', d3.forceLink(data.edges).id(d => d.id).distance(100))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(30));

    const g = svg.append('g');

    // Zoom
    svg.call(d3.zoom().scaleExtent([0.1, 4]).on('zoom', (e) => {
        g.attr('transform', e.transform);
    }));

    // Edges
    const link = g.selectAll('.edge')
        .data(data.edges)
        .join('line')
        .attr('class', d => {
            let cls = 'edge';
            if (d.relation === 'pulled') cls += ' edge-pulled';
            const targetNode = data.nodes.find(n => n.id === (typeof d.target === 'object' ? d.target.id : d.target));
            if (targetNode && polyScopes.has(targetNode.id)) cls += ' edge-polymorphism';
            return cls;
        });

    // Nodes
    const nodeSize = d => d.type === 'user' ? 14 : d.type === 'scope' ? 10 : 8;
    const nodeClass = d => {
        if (d.type === 'user') return 'node-user';
        if (d.type === 'scope') return 'node-scope' + (polyScopes.has(d.id) ? ' polymorphism-glow' : '');
        return `node-event node-event-${d.event_type || 'change'}`;
    };

    const node = g.selectAll('.node')
        .data(data.nodes)
        .join('g')
        .attr('class', 'node')
        .call(d3.drag()
            .on('start', (e, d) => { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
            .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
            .on('end', (e, d) => { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; })
        );

    node.each(function(d) {
        const el = d3.select(this);
        if (d.type === 'user') {
            el.append('circle').attr('r', nodeSize(d)).attr('class', nodeClass(d));
        } else if (d.type === 'scope') {
            el.append('rect')
                .attr('width', nodeSize(d) * 2).attr('height', nodeSize(d) * 2)
                .attr('x', -nodeSize(d)).attr('y', -nodeSize(d))
                .attr('rx', 2)
                .attr('class', nodeClass(d));
        } else {
            el.append('rect')
                .attr('width', nodeSize(d) * 2).attr('height', nodeSize(d) * 2)
                .attr('x', -nodeSize(d)).attr('y', -nodeSize(d))
                .attr('rx', 1)
                .attr('class', nodeClass(d));
        }
    });

    // Labels
    node.append('text')
        .attr('class', 'node-label')
        .attr('dy', d => nodeSize(d) + 14)
        .attr('text-anchor', 'middle')
        .text(d => (d.label || d.id).substring(0, 30));

    // Click handler
    node.on('click', (e, d) => {
        const panel = document.getElementById('detail-panel');
        panel.classList.remove('hidden');
        document.getElementById('detail-content').textContent = JSON.stringify(d, null, 2);
    });

    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
    });
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
