document.addEventListener('DOMContentLoaded', function() {
    fetch('/admin/api/screenshots')
        .then(resp => resp.json())
        .then(data => buildTree(data));

    function buildTree(data) {
        const tree = document.getElementById('tree-pane');
        if (!tree) return;
        const rootUl = document.createElement('ul');
        for (const platform in data) {
            const pLi = document.createElement('li');
            pLi.textContent = platform;
            const typeUl = document.createElement('ul');
            for (const type in data[platform]) {
                const tLi = document.createElement('li');
                tLi.textContent = type;
                const dateUl = document.createElement('ul');
                for (const date in data[platform][type]) {
                    const dLi = document.createElement('li');
                    dLi.textContent = date;
                    const scUl = document.createElement('ul');
                    data[platform][type][date].forEach(sc => {
                        const scLi = document.createElement('li');
                        const link = document.createElement('a');
                        link.href = '#';
                        link.textContent = sc.filename;
                        link.addEventListener('click', (e) => {
                            e.preventDefault();
                            showScreenshot(sc.id);
                        });
                        scLi.appendChild(link);
                        scUl.appendChild(scLi);
                    });
                    dLi.appendChild(scUl);
                    dateUl.appendChild(dLi);
                }
                tLi.appendChild(dateUl);
                typeUl.appendChild(tLi);
            }
            pLi.appendChild(typeUl);
            rootUl.appendChild(pLi);
        }
        tree.appendChild(rootUl);
    }

    function showScreenshot(id) {
        const img = document.getElementById('preview-image');
        img.src = '/admin/screenshot/' + id + '?t=' + Date.now();
        fetch('/admin/api/screenshot_info/' + id)
            .then(resp => resp.json())
            .then(info => {
                const div = document.getElementById('screenshot-info');
                div.textContent = 'Accepted License: ' + info.is_accepted;
            });
    }
});
