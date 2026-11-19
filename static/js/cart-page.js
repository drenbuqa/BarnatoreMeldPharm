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

    function captureItemData(cartKey) {
        var el = document.querySelector(
            '.cart-item-card[data-cart-key="' + cartKey + '"], .cart-item-row[data-cart-key="' + cartKey + '"]'
        );
        if (!el) return {};
        var name = el.dataset.itemName || (el.querySelector('.cart-item-name, .product-name') || {}).textContent || '';
        name = name.trim();
        var size = el.dataset.itemSize || (el.querySelector('.cart-item-size, .product-size') || {}).textContent || '';
        size = size.trim();
        var qtyInput = el.querySelector('.qty-input');
        var qty = qtyInput ? (parseInt(qtyInput.value) || 1) : 1;
        var meta = size ? size + ' · ' + qty + ' copë' : (qty > 1 ? qty + ' copë' : '');
        return {
            name: name,
            meta: meta,
            productId: el.dataset.itemId || '',
            variantId: el.dataset.variantId || '',
            qty: qty
        };
    }

    function setMinusMode(btn, qty) {
        if (!btn) return;
        var icon = btn.querySelector('i');
        if (!icon) return;
        if (qty <= 1) {
            btn.classList.add('qty-btn--trash');
            icon.className = 'fas fa-trash-alt';
            btn.title = 'Hiqe';
        } else {
            btn.classList.remove('qty-btn--trash');
            icon.className = 'fas fa-minus';
            btn.title = '';
        }
    }

    function initMinusButtons() {
        document.querySelectorAll('[data-decrease-form]').forEach(function (form) {
            var wrapper = form.closest('.quantity-selector, .quantity-control');
            if (!wrapper) return;
            var input = wrapper.querySelector('.qty-input');
            var qty = input ? (parseInt(input.value) || 1) : 1;
            setMinusMode(form.querySelector('.qty-btn'), qty);
        });
    }

    document.addEventListener('submit', function (e) {
        if (!e.target.hasAttribute('data-decrease-form')) return;
        var form = e.target;
        var wrapper = form.closest('.quantity-selector, .quantity-control');
        if (!wrapper) return;
        var input = wrapper.querySelector('.qty-input');
        if (!input || parseInt(input.value) > 1) return;

        e.preventDefault();
        e.stopImmediatePropagation();

        var card = form.closest('.cart-item-card, .cart-item-row');
        if (!card) return;
        var removeForm = card.querySelector('form[data-cart-remove]');
        if (removeForm) {
            removeForm.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
    }, true);

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

        var button = form.querySelector('button[type="submit"]');
        if (button) button.disabled = true;

        var cartKey = form.dataset.cartKey;
        var itemData = captureItemData(cartKey);

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

            removeEveryCartCopy(cartKey);
            applyCartTotals(data);
            if (typeof window.refreshMiniCart === 'function') window.refreshMiniCart();

            if (data.cart_count === 0) {
                try { sessionStorage.setItem('cartRemoveToast', JSON.stringify(itemData)); } catch(e) {}
                window.setTimeout(function () { window.location.reload(); }, 230);
            } else {
                if (typeof window.showCartRemoveToast === 'function') {
                    window.showCartRemoveToast(itemData);
                }
            }
        } catch (error) {
            if (button) button.disabled = false;
            if (typeof window.showToast === 'function') {
                window.showToast(error.message || 'Ndodhi një gabim gjatë largimit.', 'error');
            }
        }
    }, true);

    document.addEventListener('DOMContentLoaded', function () {
        initMinusButtons();
        if (typeof window._cartRemoveToastFromSession === 'function') {
            window._cartRemoveToastFromSession();
        }
    });
})();
