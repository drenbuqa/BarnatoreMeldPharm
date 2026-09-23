(function () {
    function money(value) {
        return '€' + (Number(value) || 0).toFixed(2);
    }

    function updateText(selector, value) {
        document.querySelectorAll(selector).forEach(function (element) {
            element.textContent = value;
        });
    }

    function removeEveryCartCopy(cartKey) {
        document.querySelectorAll('.cart-item-row[data-cart-key], .cart-item-card[data-cart-key]').forEach(function (item) {
            if (item.dataset.cartKey !== cartKey || item.dataset.removing === 'true') return;
            item.dataset.removing = 'true';
            item.style.transition = 'opacity .2s ease, transform .2s ease';
            item.style.opacity = '0';
            item.style.transform = 'translateY(-4px)';
            window.setTimeout(function () { item.remove(); }, 210);
        });
    }

    function applyCartTotals(data) {
        updateText('.summary-total-price', money(data.total_price));
        updateText('.summary-delivery-fee', data.delivery_fee > 0 ? money(data.delivery_fee) : 'Falas');
        updateText('.grand-total, .grand-total-amount, .sticky-total-amount', money(data.grand_total));

        document.querySelectorAll('.summary-total-savings').forEach(function (element) {
            element.textContent = '-' + money(data.total_savings);
            var row = element.closest('.savings-row');
            if (row) row.style.display = data.total_savings > 0 ? 'flex' : 'none';
        });

        if (typeof window.updateCartPageShippingBar === 'function') {
            window.updateCartPageShippingBar(data.total_price);
        }
        if (typeof window.updateGlobalBadges === 'function') {
            window.updateGlobalBadges(data);
        }
    }

    document.addEventListener('click', function (event) {
        var row = event.target.closest('.clickable-row[data-href]');
        if (!row) return;
        if (event.target.closest('a, button, input, select, textarea, form, label')) return;
        window.location.href = row.dataset.href;
    });

    document.addEventListener('submit', async function (event) {
        var form = event.target.closest('form[data-cart-remove]');
        if (!form) return;

        event.preventDefault();
        event.stopImmediatePropagation();

        var confirmed;
        if (window.Swal) {
            var result = await window.Swal.fire({
                title: 'A jeni i sigurt?',
                text: 'Dëshironi ta largoni këtë produkt nga shporta?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#b4534b',
                cancelButtonColor: '#64748b',
                confirmButtonText: 'Po, largoje!',
                cancelButtonText: 'Anulo'
            });
            confirmed = result.isConfirmed;
        } else {
            confirmed = window.confirm('Dëshironi ta largoni këtë produkt nga shporta?');
        }
        if (!confirmed) return;

        var button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;

        try {
            var response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            var data = await response.json();
            if (!response.ok || !data.success || !data.removed) {
                throw new Error(data.message || 'Produkti nuk u largua.');
            }

            removeEveryCartCopy(form.dataset.cartKey);
            applyCartTotals(data);
            if (typeof window.refreshMiniCart === 'function') window.refreshMiniCart();
            if (typeof window.showToast === 'function') window.showToast(data.message, 'info');

            if (data.cart_count === 0) {
                window.setTimeout(function () { window.location.reload(); }, 230);
            }
        } catch (error) {
            if (button) button.disabled = false;
            if (typeof window.showToast === 'function') {
                window.showToast(error.message || 'Ndodhi një gabim gjatë largimit.', 'error');
            }
        }
    }, true);
})();
