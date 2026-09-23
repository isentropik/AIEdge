/* Menu-only enhancements: do not start requests, captures or streams. */
document.addEventListener('DOMContentLoaded', function () {
    const menu = document.querySelector('.menu');
    if (!menu) return;
    const close = function () {
        menu.querySelectorAll('li.open').forEach(li => li.classList.remove('open'));
        menu.querySelectorAll('[aria-expanded]').forEach(a => a.setAttribute('aria-expanded', 'false'));
    };
    menu.querySelectorAll('li').forEach(li => {
        const anchor = li.querySelector(':scope > a');
        const children = li.querySelector(':scope > ul');
        if (!anchor || !children) return;
        anchor.setAttribute('role', 'button');
        anchor.setAttribute('tabindex', '0');
        anchor.setAttribute('aria-expanded', 'false');
        const toggle = function (event) {
            event.preventDefault(); event.stopPropagation();
            const open = !li.classList.contains('open');
            li.classList.toggle('open', open);
            anchor.setAttribute('aria-expanded', String(open));
        };
        anchor.addEventListener('click', toggle);
        anchor.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') toggle(event);
            if (event.key === 'Escape') { close(); anchor.focus(); }
        });
    });
    menu.querySelectorAll('a[onclick]').forEach(a => a.addEventListener('click', close));
    document.addEventListener('click', event => { if (!menu.contains(event.target)) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') close(); });
});
