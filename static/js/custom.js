// Thunder FC — Custom JS

// ── Toast notifications ───────────────────────────────────────────────────
const Toast = (() => {
    let container;

    function getContainer() {
        if (!container) {
            container = document.createElement('div');
            container.style.cssText = `
                position: fixed; top: 20px; right: 20px;
                z-index: 9999; display: flex; flex-direction: column; gap: 10px;
            `;
            document.body.appendChild(container);
        }
        return container;
    }

    function show(message, type = 'info', duration = 4000) {
        const colors = {
            success: { bg: 'rgba(0,200,81,0.1)', border: '#00c851', text: '#69f0ae', icon: '✅' },
            error:   { bg: 'rgba(255,71,87,0.1)', border: '#ff4757', text: '#ff6b6b', icon: '❌' },
            warning: { bg: 'rgba(255,165,0,0.1)', border: '#ffa502', text: '#ffb74d', icon: '⚠️' },
            info:    { bg: 'rgba(100,149,237,0.1)', border: '#6495ed', text: '#90caf9', icon: 'ℹ️' },
        };

        const c = colors[type] || colors.info;
        const toast = document.createElement('div');
        toast.style.cssText = `
            background: ${c.bg};
            border: 1px solid ${c.border};
            border-left: 3px solid ${c.border};
            color: ${c.text};
            padding: 14px 18px;
            border-radius: 10px;
            font-family: 'DM Sans', sans-serif;
            font-size: 13px;
            min-width: 280px;
            max-width: 360px;
            backdrop-filter: blur(10px);
            display: flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            transform: translateX(120%);
            transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.3s;
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        `;

        toast.innerHTML = `<span>${c.icon}</span><span>${message}</span>`;
        getContainer().appendChild(toast);

        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                toast.style.transform = 'translateX(0)';
            });
        });

        const dismiss = () => {
            toast.style.transform = 'translateX(120%)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 350);
        };

        toast.addEventListener('click', dismiss);
        if (duration > 0) setTimeout(dismiss, duration);

        return { dismiss };
    }

    return { show };
})();


// ── Page transition ───────────────────────────────────────────────────────
function setupPageTransitions() {
    document.querySelectorAll('a[href]').forEach(link => {
        const href = link.getAttribute('href');
        if (!href || href.startsWith('#') || href.startsWith('javascript') || link.target === '_blank') return;
        if (link.hasAttribute('data-no-transition')) return;

        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            e.preventDefault();
            document.body.style.transition = 'opacity 0.2s ease';
            document.body.style.opacity = '0';
            setTimeout(() => { window.location.href = href; }, 200);
        });
    });

    // Fade in on load
    document.body.style.opacity = '0';
    document.body.style.transition = 'opacity 0.3s ease';
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            document.body.style.opacity = '1';
        });
    });
}


// ── Animated number counter ───────────────────────────────────────────────
function animateCounter(el, target, decimals = 0, duration = 1000) {
    const start = parseFloat(el.textContent) || 0;
    const diff = target - start;
    const startTime = performance.now();

    function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // Ease out cubic
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = (start + diff * eased).toFixed(decimals);
        if (progress < 1) requestAnimationFrame(update);
    }

    requestAnimationFrame(update);
}


// ── Scroll reveal ─────────────────────────────────────────────────────────
function setupScrollReveal() {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.animation = 'fadeUp 0.5s ease both';
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1 });

    document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
}


// ── Number input bounds ───────────────────────────────────────────────────
function setupNumericInputs() {
    document.querySelectorAll('input[type="number"]').forEach(input => {
        input.addEventListener('change', function() {
            const min = parseFloat(this.min);
            const max = parseFloat(this.max);
            const val = parseFloat(this.value);
            if (!isNaN(min) && val < min) this.value = min;
            if (!isNaN(max) && val > max) this.value = max;
        });

        // Visual feedback on focus
        input.addEventListener('focus', function() {
            this.style.transition = 'all 0.25s';
        });
    });
}


// ── Confirm dialogs (nicer than native confirm) ───────────────────────────
function setupDeleteConfirms() {
    document.querySelectorAll('[data-confirm]').forEach(el => {
        el.addEventListener('click', function(e) {
            e.preventDefault();
            const msg = this.dataset.confirm || 'Are you sure?';
            if (window.confirm(msg)) {
                window.location.href = this.href;
            }
        });
    });
}


// ── Clipboard copy ────────────────────────────────────────────────────────
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        Toast.show('Copied to clipboard', 'success', 2500);
    }).catch(() => {
        Toast.show('Failed to copy', 'error');
    });
}


// ── Utilities ─────────────────────────────────────────────────────────────
function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('en-US', {
        year: 'numeric', month: 'short', day: 'numeric'
    });
}

function formatScore(score) {
    return parseFloat(score).toFixed(2);
}


// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    setupPageTransitions();
    setupScrollReveal();
    setupNumericInputs();
    setupDeleteConfirms();

    // Animate all counters with data-count attribute
    document.querySelectorAll('[data-count]').forEach(el => {
        const target = parseFloat(el.dataset.count);
        const decimals = el.dataset.decimals ? parseInt(el.dataset.decimals) : 0;
        animateCounter(el, target, decimals);
    });
});


// ── Expose globally ───────────────────────────────────────────────────────
window.ThunderFC = {
    Toast,
    animateCounter,
    copyToClipboard,
    formatDate,
    formatScore
};