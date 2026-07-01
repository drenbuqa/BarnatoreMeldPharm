// --- GLOBAL HELPERS ---
// Inject Cloudinary auto-format/auto-quality + width transforms so images sent
// from JS-rendered cards (filtering, pagination, load-more) aren't served at
// full original resolution like raw pasted admin URLs are.
window.cldUrl = function (url, width) {
    if (!url || url.indexOf('res.cloudinary.com') === -1 || url.indexOf('/upload/') === -1) return url;
    if (/\/upload\/[^/]*f_auto/.test(url)) return url;
    const transform = width ? `f_auto,q_auto,w_${width}` : 'f_auto,q_auto';
    return url.replace('/upload/', `/upload/${transform}/`);
};

window.updateResultsCount = function (count) {
    const countEl = document.getElementById('current-count');
    if (countEl) countEl.textContent = count;
};

window.createProductCardHtml = function (p) {
    const discountPercentage = p.discount_price ? Math.round(((p.price - p.discount_price) / p.price) * 100) : 0;
    const discountBadgeText = p.offer_badge_text && !String(p.offer_badge_text).startsWith('-')
        ? p.offer_badge_text
        : (p.discount_price ? `-${discountPercentage}%` : '');
    const isFav = p.is_favorite ? 'active' : '';
    const heartIconClass = p.is_favorite ? 'fas' : 'far';
    return `
        <div class="product-card fade-in-section" data-id="${p.id}" data-category="${p.category}" data-name="${p.name}">
            <div class="product-image">
                ${p.discount_price ? `<div class="special-offer-badge red-badge">Oferta Speciale</div>` : ''}
                ${p.is_best_seller ? `<div class="best-seller-badge">Më i Shituri</div>` : ''}
                ${p.is_pharmacist_choice ? `<div class="pharmacist-badge"><i class="fas fa-user-md"></i> Farmacisti</div>` : ''}
                <img src="${window.cldUrl(p.image_url, 400)}" alt="${p.name}" class="loading" onload="this.classList.remove('loading'); this.classList.add('loaded');">
                <button class="btn-favorite ${isFav}" onclick="toggleFavorite(this, '${p.id}')">
                    <i class="${heartIconClass} fa-heart"></i>
                </button>
                <a href="/product/${p.id}" class="product-card-link-overlay"></a>
            </div>
            <div class="product-info">
                <span class="product-category" style="color: var(--primary); font-weight: 700;">${p.brand || p.category}</span>
                <h3 class="product-title">${p.name}</h3>
                ${p.size ? `<span class="product-size">${p.size}</span>` : ''}
                <div class="price-container">
                    ${p.discount_price ? `
                        <span class="price discounted">€${parseFloat(p.discount_price).toFixed(2)}</span>
                        <span class="price original">€${parseFloat(p.price).toFixed(2)}</span>
                        <span class="discount-badge">${discountBadgeText}</span>
                    ` : `<span class="price">€${parseFloat(p.price).toFixed(2)}</span>`}
                </div>
            </div>
        </div>
    `;
};

window.renderProducts = function (products, grid) {
    if (!grid) return;
    grid.innerHTML = products.map(p => window.createProductCardHtml(p)).join('');

    // Trigger visibility for fade-in animations
    const cards = grid.querySelectorAll('.product-card');
    if (cards.length > 0) {
        setTimeout(() => {
            cards.forEach(card => card.classList.add('visible'));
        }, 50);
    }
};

window.appendProducts = function (products, grid) {
    if (!grid) return;
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = products.map(p => window.createProductCardHtml(p)).join('');

    while (tempDiv.firstChild) {
        const child = tempDiv.firstChild;
        grid.appendChild(child);
        // Trigger visibility if intersection observer is not used for These new items
        setTimeout(() => child.classList.add('visible'), 50);
    }
};

window.createSkeletonHtml = function () {
    return `
        <div class="skeleton-card">
            <div class="skeleton skeleton-img"></div>
            <div class="skeleton skeleton-text header"></div>
            <div class="skeleton skeleton-text"></div>
            <div class="skeleton skeleton-text short"></div>
            <div style="margin-top: auto; display: flex; justify-content: space-between; align-items: center; padding-top: 1rem;">
                <div class="skeleton skeleton-text" style="width: 80px; margin-bottom: 0;"></div>
                <div class="skeleton" style="width: 40px; height: 40px; border-radius: 50%;"></div>
            </div>
        </div>
    `;
};

window.createSearchSkeletonHtml = function () {
    return `
        <div class="preview-item" style="gap: 1rem; padding: 10px 15px;">
            <div class="skeleton" style="width: 40px; height: 40px; border-radius: 4px; flex-shrink: 0;"></div>
            <div style="flex-grow: 1;">
                <div class="skeleton skeleton-text" style="width: 80%; height: 0.8rem; margin-bottom: 5px;"></div>
                <div class="skeleton skeleton-text" style="width: 40%; height: 0.7rem; margin-bottom: 0;"></div>
            </div>
        </div>
    `;
};


window.renderSkeletons = function (grid, count = 10, append = false) {
    if (!grid) return;
    const skeletons = Array(count).fill(0).map(() => window.createSkeletonHtml()).join('');
    if (append) {
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = skeletons;
        while (tempDiv.firstChild) {
            grid.appendChild(tempDiv.firstChild);
        }
    } else {
        grid.innerHTML = skeletons;
    }
};


window.loadMoreHome = function () {
    const btn = document.getElementById('load-more-btn');
    const grid = document.getElementById('recommended-grid');
    if (!btn || !grid) return;

    // Show skeletons immediately
    window.renderSkeletons(grid, 20);

    // Hide button while loading
    btn.parentElement.classList.add('d-none');

    const category = btn.getAttribute('data-category') || 'all';
    let url = `/products?ajax=1&all=true`;
    if (category !== 'all') {
        url += `&category=${encodeURIComponent(category)}`;
    }

    fetch(url)
        .then(res => res.json())
        .then(data => {
            if (data.products && data.products.length > 0) {
                grid.innerHTML = '';
                window.appendProducts(data.products, grid);
            }
        })
        .catch(err => {
            console.error('Error loading more home:', err);
            btn.parentElement.classList.remove('d-none');
        });
};

// --- GLOBAL UI HANDLERS (Available immediately) ---
window.openShopSidebar = function () {
    const sidebar = document.getElementById('shopSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const mobileHeader = document.querySelector('.mobile-header');
    const mobileBottomNav = document.querySelector('.mobile-bottom-nav');

    if (sidebar) sidebar.classList.add('active');
    if (overlay) overlay.classList.add('active');

    // Disable scrolling but don't hide menus yet to avoid jitter
    document.body.classList.add('sidebar-open');

    // Re-render price slider now that sidebar is visible (hidden = zero width during DOMContentLoaded)
    requestAnimationFrame(function() {
        if (!window._priceSliderInited) {
            window.initPriceSlider();
        } else if (window._priceSliderRender) {
            window._priceSliderRender();
        }
    });
};

window.closeShopSidebar = function () {
    const sidebar = document.getElementById('shopSidebar');
    const overlay = document.getElementById('sidebarOverlay');

    if (sidebar) sidebar.classList.remove('active');
    if (overlay) overlay.classList.remove('active');

    document.body.classList.remove('sidebar-open');
};

// Toggle Filter Sections (Collapsible)
window.toggleFilterSection = function (btn) {
    const parent = btn.closest('.collapsible-sidebar-block');
    const icon = btn.querySelector('i');

    if (parent.classList.contains('active')) {
        parent.classList.remove('active');
        icon.classList.replace('fa-chevron-up', 'fa-chevron-down');
    } else {
        parent.classList.add('active');
        icon.classList.replace('fa-chevron-down', 'fa-chevron-up');
    }
};

window.toggleSubcats = function (event, btn) {
    // Determine which argument is the button/element
    let targetElement = btn;
    let ev = event;

    if (btn === undefined && event) {
        // Called via onclick="toggleSubcats(this)"
        targetElement = event;
        ev = null;
    }

    if (ev && typeof ev.preventDefault === 'function') {
        ev.preventDefault();
        ev.stopPropagation();
    }

    if (!targetElement) return;

    // Handle Mobile Category Modal
    const mobileItem = targetElement.closest('.mobile-cat-item');
    if (mobileItem) {
        mobileItem.classList.toggle('open');
        return;
    }

    // Handle Desktop/Sidebar
    const group = targetElement.closest('.sidebar-cat-group');
    if (group) {
        const list = group.querySelector('.sidebar-subcat-list');
        const icon = targetElement.querySelector('.toggle-icon');

        if (list) list.classList.toggle('show');
        if (icon) icon.classList.toggle('rotated');
    }
};

// ── Dual-handle price range slider ──────────────────────────
window._priceSliderInited = false;
window._syncPriceSlider = function() {};

window.initPriceSlider = function() {
    const sliderMin = document.getElementById('range-slider-min');
    const sliderMax = document.getElementById('range-slider-max');
    const fill      = document.getElementById('prs-fill');
    const minDisp   = document.getElementById('price-min-display');
    const maxDisp   = document.getElementById('price-max-display');
    const hidMin    = document.getElementById('min-price');
    const hidMax    = document.getElementById('max-price');
    if (!sliderMin || !sliderMax || !fill) return;

    const SLIDER_MIN = parseInt(sliderMin.min, 10);
    const SLIDER_MAX = parseInt(sliderMin.max, 10);

    // Set handles from existing URL params, guaranteeing at least 1 step between them
    const initMin = parseInt(hidMin.value) || SLIDER_MIN;
    const initMax = parseInt(hidMax.value) || SLIDER_MAX;
    let startLo = Math.max(SLIDER_MIN, Math.min(initMin, SLIDER_MAX));
    let startHi = Math.max(SLIDER_MIN, Math.min(initMax, SLIDER_MAX));
    if (startLo >= startHi) startLo = Math.max(SLIDER_MIN, startHi - 1);
    sliderMin.value = startLo;
    sliderMax.value = startHi;

    function render() {
        let lo = parseInt(sliderMin.value, 10);
        let hi = parseInt(sliderMax.value, 10);
        const span = SLIDER_MAX - SLIDER_MIN;
        const lPct = ((lo - SLIDER_MIN) / span) * 100;
        const rPct = 100 - ((hi - SLIDER_MIN) / span) * 100;

        fill.style.left  = 'calc(' + lPct + '% + 8px)';
        fill.style.right = 'calc(' + rPct + '% + 8px)';

        minDisp.textContent = lo + '€';
        maxDisp.textContent = hi + '€';

        minDisp.classList.toggle('active', lo > SLIDER_MIN);
        maxDisp.classList.toggle('active', hi < SLIDER_MAX);

        // When min is pushed to the right edge, bring it on top so user can drag it back left
        sliderMin.style.zIndex = (lo >= hi) ? 3 : 2;
        sliderMax.style.zIndex = (lo >= hi) ? 2 : 3;
    }

    // Re-reads hidden inputs and repositions thumbs — safe to call when sidebar becomes visible
    window._priceSliderRender = function() {
        const curMin = parseInt(hidMin.value) || SLIDER_MIN;
        const curMax = parseInt(hidMax.value) || SLIDER_MAX;
        sliderMin.value = Math.max(SLIDER_MIN, Math.min(curMin, SLIDER_MAX));
        sliderMax.value = Math.max(SLIDER_MIN, Math.min(curMax, SLIDER_MAX));
        render();
    };

    // Expose so resetFilters can call it
    window._syncPriceSlider = function() {
        sliderMin.value = SLIDER_MIN;
        sliderMax.value = SLIDER_MAX;
        render();
    };

    function clampAndRender() {
        let lo = parseInt(sliderMin.value, 10);
        let hi = parseInt(sliderMax.value, 10);
        // Enforce minimum 1-step gap so the two thumbs never sit on the same spot
        if (this === sliderMin && lo >= hi) {
            lo = Math.max(SLIDER_MIN, hi - 1);
            sliderMin.value = lo;
        } else if (this === sliderMax && hi <= lo) {
            hi = Math.min(SLIDER_MAX, lo + 1);
            sliderMax.value = hi;
        }
        render();
    }

    function applyFilter() {
        clampAndRender.call(this);
        const lo = parseInt(sliderMin.value, 10);
        const hi = parseInt(sliderMax.value, 10);
        hidMin.value = lo > SLIDER_MIN ? lo : '';
        hidMax.value = hi < SLIDER_MAX ? hi : '';
        if (window.updateShop) window.updateShop();
    }

    sliderMin.addEventListener('input',  function() { sliderMin.style.zIndex = 3; sliderMax.style.zIndex = 2; clampAndRender.call(this); });
    sliderMax.addEventListener('input',  function() { sliderMax.style.zIndex = 3; sliderMin.style.zIndex = 2; clampAndRender.call(this); });
    sliderMin.addEventListener('change', function() { applyFilter.call(this); });
    sliderMax.addEventListener('change', function() { applyFilter.call(this); });

    render(); // draw initial state
    window._priceSliderInited = true;
};

window.resetFilters = function (e) {
    if (e) e.preventDefault();

    // Clear inputs
    const minPrice = document.getElementById('min-price');
    const maxPrice = document.getElementById('max-price');
    if (minPrice) minPrice.value = '';
    if (maxPrice) maxPrice.value = '';

    // Reset slider visuals
    if (window._priceSliderInited) window._syncPriceSlider();

    const discountOnly = document.getElementById('discount-only-filter');
    if (discountOnly) discountOnly.checked = false;

    const bestSellers = document.getElementById('best-seller-filter');
    if (bestSellers) bestSellers.checked = false;

    const productSearch = document.getElementById('productSearch');
    const productSearchMobile = document.getElementById('productSearchMobile');
    if (productSearch) productSearch.value = '';
    if (productSearchMobile) productSearchMobile.value = '';

    // Reset URL and call update
    const url = new URL(window.location.href);
    url.search = '';
    window.history.pushState({}, '', url.pathname);

    // Update UI active states
    document.querySelectorAll('.sidebar-cat-link, .sidebar-subcat-link, .brand-link-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.sidebar-cat-link[onclick*="\'all\'"], .brand-link-item[onclick*="\'all\'"]').forEach(el => el.classList.add('active'));

    window.updateShop();
};

window.filterByCategory = function (e, cat) {
    if (e) e.preventDefault();
    const urlParams = new URLSearchParams(window.location.search);
    if (cat === 'all') {
        urlParams.delete('category');
    } else {
        urlParams.set('category', cat);
    }
    urlParams.delete('subcategory');
    urlParams.delete('brand');
    urlParams.delete('page');

    // Clear custom programmatic search injected by banners so regular browsing isn't stuck
    const productSearch = document.getElementById('productSearch');
    const productSearchMobile = document.getElementById('productSearchMobile');
    let hasAdvancedSearch = false;
    if (productSearch && productSearch.value.includes(',')) hasAdvancedSearch = true;
    if (productSearchMobile && productSearchMobile.value.includes(',')) hasAdvancedSearch = true;
    
    if (hasAdvancedSearch) {
        if (productSearch) productSearch.value = '';
        if (productSearchMobile) productSearchMobile.value = '';
        urlParams.delete('search');
    }

    // Also clear it cleanly from the URL so it dies when we pushState
    const cleanParams = new URLSearchParams(urlParams.toString());
    window.history.pushState({}, '', `${window.location.pathname}?${cleanParams.toString()}`);

    // Update active classes
    document.querySelectorAll('.sidebar-cat-link').forEach(link => {
        const onclick = link.getAttribute('onclick') || '';
        const escaped = cat.replace(/'/g, "\\'");
        if (onclick.includes(`'${escaped}'`) || onclick.includes(`'${cat}'`)) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
    document.querySelectorAll('.sidebar-subcat-list').forEach(list => {
        list.classList.remove('show');
    });
    document.querySelectorAll('.toggle-icon').forEach(ico => {
        ico.classList.remove('rotated');
    });

    const activeLink = document.querySelector(`.sidebar-cat-link.active`);
    if (activeLink) {
        const activeGroup = activeLink.closest('.sidebar-cat-group');
        if (activeGroup) {
            const activeList = activeGroup.querySelector('.sidebar-subcat-list');
            const activeIcon = activeGroup.querySelector('.toggle-icon');
            if (activeList) activeList.classList.add('show');
            if (activeIcon) activeIcon.classList.add('rotated');
        }
    }

    document.querySelectorAll('.sidebar-subcat-link').forEach(link => link.classList.remove('active'));

    window.updateShop();
};

window.filterBySubcategory = function (e, cat, sub) {
    if (e) e.preventDefault();
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('category', cat);
    urlParams.set('subcategory', sub);
    urlParams.delete('page');

        // Clear custom programmatic search injected by banners so regular browsing isn't stuck
    const productSearch = document.getElementById('productSearch');
    const productSearchMobile = document.getElementById('productSearchMobile');
    let hasAdvancedSearch = false;
    if (productSearch && productSearch.value.includes(',')) hasAdvancedSearch = true;
    if (productSearchMobile && productSearchMobile.value.includes(',')) hasAdvancedSearch = true;
    
    if (hasAdvancedSearch) {
        if (productSearch) productSearch.value = '';
        if (productSearchMobile) productSearchMobile.value = '';
        urlParams.delete('search');
    }
    window.history.pushState({}, '', `${window.location.pathname}?${urlParams.toString()}`);

    // Update active classes
    document.querySelectorAll('.sidebar-cat-link').forEach(link => {
        const onclick = link.getAttribute('onclick') || '';
        const escaped = cat.replace(/'/g, "\\'");
        if (onclick.includes(`'${escaped}'`) || onclick.includes(`'${cat}'`)) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
    document.querySelectorAll('.sidebar-subcat-link').forEach(link => {
        const onclick = link.getAttribute('onclick');
        if (onclick) {
            link.classList.toggle('active', onclick.includes(`'${sub}'`));
        }
    });

    window.updateShop();
};

window.filterByBrand = function (e, brand) {
    if (e) e.preventDefault();
    const urlParams = new URLSearchParams(window.location.search);
    if (brand === 'all') {
        urlParams.delete('brand');
    } else {
        urlParams.set('brand', brand);
    }
    urlParams.delete('page');

        // Clear custom programmatic search injected by banners so regular browsing isn't stuck
    const productSearch = document.getElementById('productSearch');
    const productSearchMobile = document.getElementById('productSearchMobile');
    let hasAdvancedSearch = false;
    if (productSearch && productSearch.value.includes(',')) hasAdvancedSearch = true;
    if (productSearchMobile && productSearchMobile.value.includes(',')) hasAdvancedSearch = true;
    
    if (hasAdvancedSearch) {
        if (productSearch) productSearch.value = '';
        if (productSearchMobile) productSearchMobile.value = '';
        urlParams.delete('search');
    }
    window.history.pushState({}, '', `${window.location.pathname}?${urlParams.toString()}`);

    // Update active classes
    document.querySelectorAll('.brand-link-item').forEach(link => {
        const onclick = link.getAttribute('onclick') || '';
        const escapedForDisplay = brand.replace(/'/g, "\\'");
        if (onclick.includes(`'${escapedForDisplay}'`) || onclick.includes(`"${brand.replace(/\"/g, '\\"')}”`)) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    window.updateShop();
};

window.toggleSortMenu = function (e) {
    if (e) {
        if (typeof e.preventDefault === 'function') e.preventDefault();
        if (typeof e.stopPropagation === 'function') e.stopPropagation();
    }
    const sortMenu = document.getElementById('sortMenu');
    const sortTrigger = document.getElementById('sortTrigger');
    if (sortMenu && sortTrigger) {
        const isVisible = sortMenu.style.display === 'block' || sortMenu.classList.contains('show');
        if (isVisible) {
            sortMenu.style.display = 'none';
            sortMenu.classList.remove('show');
            sortTrigger.classList.remove('active');
        } else {
            sortMenu.style.display = 'block';
            sortMenu.classList.add('show');
            sortTrigger.classList.add('active');
        }
    }
};

window.updateShop = function (isLoadMore = false, loadAll = false) {
    const productGrid = document.getElementById('productGrid');
    if (!productGrid) return;

    const loadMoreBtn = document.getElementById('load-more-products');
    let page = 1;
    if (isLoadMore && loadMoreBtn && !loadAll) {
        page = (parseInt(loadMoreBtn.getAttribute('data-page')) || 1) + 1;
    }

    const urlParams = new URLSearchParams(window.location.search);
    if (loadAll) {
        urlParams.set('all', 'true');
    }

    // Set search if exists in input, or delete it if input is empty (so clearing search clears the query)
    const searchInput = document.getElementById('adminOrderSearch') || document.getElementById('productSearch');
    if (searchInput) {
        if (searchInput.value) {
            urlParams.set('search', searchInput.value);
        } else {
            urlParams.delete('search');
        }
    }

    const minPrice = document.getElementById('min-price'), maxPrice = document.getElementById('max-price');
    if (minPrice && minPrice.value) {
        urlParams.set('min_price', minPrice.value);
    } else {
        urlParams.delete('min_price');
    }

    if (maxPrice && maxPrice.value) {
        urlParams.set('max_price', maxPrice.value);
    } else {
        urlParams.delete('max_price');
    }

    const discountOnly = document.getElementById('discount-only-filter');
    if (discountOnly && discountOnly.checked) urlParams.set('discount_only', 'true');

    const bestSellers = document.getElementById('best-seller-filter');
    if (bestSellers && bestSellers.checked) urlParams.set('best_sellers', 'true');

    const pharmacistChoice = document.getElementById('pharmacist-choice-filter');
    if (pharmacistChoice && pharmacistChoice.checked) urlParams.set('pharmacist_choice', 'true');

    urlParams.set('ajax', '1');
    urlParams.set('page', page);

    if (!isLoadMore && !loadAll) {
        window.renderSkeletons(productGrid, 12);
    } else if (isLoadMore) {
        // Append skeletons at the end
        window.renderSkeletons(productGrid, 4, true);
    }

    // Show loading state on button
    let originalBtnText = '';
    if ((isLoadMore || loadAll) && loadMoreBtn) {
        originalBtnText = loadMoreBtn.innerHTML;
        loadMoreBtn.disabled = true;
        loadMoreBtn.innerHTML = 'Duke u ngarkuar... <i class="fas fa-spinner fa-spin ml-2"></i>';
    }

    const currentPath = window.location.pathname.includes('/products') ? window.location.pathname : '/products';

    const mobileBtn = document.getElementById('closeSidebarAlt');
    if (mobileBtn) {
        mobileBtn.innerHTML = 'Duke u ngarkuar... <i class="fas fa-spinner fa-spin ml-2"></i>';
    }

    fetch(`${currentPath}?${urlParams.toString()}`)
        .then(res => res.json())
        .then(data => {
            // Remove skeletons
            const skeletons = productGrid.querySelectorAll('.skeleton-card');
            skeletons.forEach(s => s.remove());

            if (isLoadMore || loadAll) {
                if (data.products && data.products.length > 0) {
                    if (loadAll) productGrid.innerHTML = '';
                    window.appendProducts(data.products, productGrid);
                    if (loadMoreBtn) loadMoreBtn.setAttribute('data-page', page);
                }
            } else {
                window.renderProducts(data.products, productGrid);
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }

            window.updateResultsCount(data.total_count);
            // Update mobile sidebar button to reflect loading
            const mobileBtn = document.getElementById('closeSidebarAlt');
            if (mobileBtn) {
                mobileBtn.innerHTML = `Shiko ${data.total_count || 0} Produkte`;
            }

            // Update Brands Filter UI
            if (data.available_brands) {
                const brandList = document.querySelector('.brand-list');
                if (brandList) {
                    const currentBrand = new URLSearchParams(window.location.search).get('brand') || 'all';
                    let brandHtml = `<li><a href="#" onclick="filterByBrand(event, 'all')" class="brand-link-item ${currentBrand === 'all' ? 'active' : ''}">Të gjitha brendet <i class="fas fa-check"></i></a></li>`;
                    data.available_brands.forEach(brand => {
                        const escapedBrand = brand.replace(/'/g, "\\'");
                        const isActive = currentBrand === brand;
                        brandHtml += `<li><a href="#" onclick="filterByBrand(event, '${escapedBrand}')" class="brand-link-item ${isActive ? 'active' : ''}">${brand} ${isActive ? '<i class="fas fa-check"></i>' : ''}</a></li>`;
                    });
                    brandList.innerHTML = brandHtml;
                }
            }

            if (loadMoreBtn) {
                const totalPages = data.total_pages || 1;
                const currentPage = isLoadMore ? page : 1;
                if (currentPage >= totalPages || loadAll) {
                    loadMoreBtn.parentElement.classList.add('d-none');
                } else {
                    loadMoreBtn.parentElement.classList.remove('d-none');
                    loadMoreBtn.setAttribute('data-page', currentPage);
                }
            }

            if (!isLoadMore && !loadAll) {
                urlParams.delete('ajax');
                window.history.pushState({}, '', `${currentPath}?${urlParams.toString()}`);
            }
        })
        .catch(err => console.error('Error updating shop:', err))
        .finally(() => {
            productGrid.style.opacity = '1';
            const sortMenu = document.getElementById('sortMenu');
            if (sortMenu) sortMenu.classList.remove('show');
            if ((isLoadMore || loadAll) && loadMoreBtn) {
                loadMoreBtn.disabled = false;
                loadMoreBtn.innerHTML = originalBtnText;
            }
        });
};

window.filterHomeCategory = function (category, btnElement) {
    // UI update for chips
    document.querySelectorAll('.category-chip').forEach(c => c.classList.remove('active'));
    if (btnElement) btnElement.classList.add('active');

    const grid = document.getElementById('recommended-grid');
    const loadMoreBtn = document.getElementById('load-more-btn');
    if (!grid) return;

    // Show skeletons instead of just dimming
    window.renderSkeletons(grid, 5);

    let url = `/products?page=1&ajax=1`;
    if (category !== 'all') {
        url += `&category=${encodeURIComponent(category)}`;
    }

    fetch(url)
        .then(res => res.json())
        .then(data => {
            grid.innerHTML = '';
            if (data.products && data.products.length > 0) {
                window.appendProducts(data.products, grid);
                if (loadMoreBtn) {
                    loadMoreBtn.setAttribute('data-page', '1');
                    loadMoreBtn.setAttribute('data-category', category);
                    if (1 >= data.total_pages) {
                        loadMoreBtn.parentElement.classList.add('d-none');
                    } else {
                        loadMoreBtn.parentElement.classList.remove('d-none');
                    }
                }
            } else {
                grid.innerHTML = '<div class="no-products-found" style="grid-column: 1/-1; text-align: center; padding: 3rem; color: #64748b;">Nuk u gjet asnjë produkt në këtë kategori.</div>';
                if (loadMoreBtn) loadMoreBtn.parentElement.classList.add('d-none');
            }
        })
        .catch(err => console.error('Error filtering home:', err));
};

document.addEventListener('DOMContentLoaded', () => {
    // Clickable rows handler (e.g. in cart)
    const sidebar = document.getElementById('shopSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const closeBtn = document.getElementById('closeSidebar');
    const closeBtnAlt = document.getElementById('closeSidebarAlt');

    if (closeBtn) closeBtn.onclick = function () { window.closeShopSidebar(); };
    if (closeBtnAlt) closeBtnAlt.onclick = function () { window.closeShopSidebar(); };
    if (overlay) overlay.onclick = function () { window.closeShopSidebar(); };

    // Clickable rows handler (e.g. in cart)
    const hasIntersectionObserver = 'IntersectionObserver' in window;

    // --- FADE-IN ANIMATION OBSERVER ---
    if (hasIntersectionObserver) {
        const fadeObserverOptions = {
            threshold: 0.1,
            rootMargin: "0px 0px -50px 0px"
        };

        const fadeObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        }, fadeObserverOptions);

        // Function to observe all current fade-in sections
        const observeSections = () => {
            document.querySelectorAll('.fade-in-section:not(.visible)').forEach(section => {
                fadeObserver.observe(section);
            });
        };

        observeSections();
    } else {
        // Fallback for older browsers
        document.querySelectorAll('.fade-in-section').forEach(s => s.classList.add('visible'));
    }

    // --- SEARCH FOCUS HANDLER ---
    document.querySelectorAll('input[type="text"][id*="Search"]').forEach(input => {
        input.addEventListener('focus', function (e) {
            if (window.innerWidth <= 768) {
                setTimeout(() => {
                    const elementPosition = this.getBoundingClientRect().top + window.scrollY;
                    const offsetPosition = elementPosition - 80;
                    window.scrollTo({
                        top: offsetPosition,
                        behavior: 'smooth'
                    });
                }, 300);
            }
        });
    });

    // --- NAVIGATION LOGIC ---
    // Close desktop dropdowns when clicking outside
    document.addEventListener('click', function (event) {
        // Profile Dropdown
        const profileDropdown = document.getElementById('desktopProfileDropdown');
        const profileBtn = document.querySelector('.profile-dropdown-btn');
        if (profileDropdown && profileDropdown.classList.contains('active')) {
            if (!profileDropdown.contains(event.target) && (!profileBtn || !profileBtn.contains(event.target))) {
                profileDropdown.classList.remove('active');
                if (profileBtn) profileBtn.classList.remove('active');
            }
        }

        // Mini Cart Dropdown
        const miniCart = document.getElementById('miniCart');
        const cartBtn = document.getElementById('cartBadgeBtn');
        if (miniCart && miniCart.classList.contains('active')) {
            // Check if click is outside the cart container
            if (!miniCart.contains(event.target) && (!cartBtn || !cartBtn.contains(event.target))) {
                miniCart.classList.remove('active');
            }
        }
    });

    // Mobile Header Scroll Effect
    const mobileHeader = document.querySelector('.mobile-header');
    if (mobileHeader) {
        const handleScroll = () => {
            if (window.scrollY > 50) {
                mobileHeader.classList.add('scrolled');
            } else {
                mobileHeader.classList.remove('scrolled');
            }
        };
        handleScroll();
        window.addEventListener('scroll', handleScroll);
    }

    // Sticky Navbar (Desktop)
    const navbar = document.querySelector('.desktop-header');
    if (navbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 50) {
                navbar.classList.add('scrolled');
            } else {
                navbar.classList.remove('scrolled');
            }
        });
    }

    // --- SEARCH & FILTER LOGIC ---
    const searchInputs = [document.getElementById('productSearch'), document.getElementById('productSearchMobile')];
    const searchPreviews = [document.getElementById('searchPreview'), document.getElementById('searchPreviewMobile')];
    const filterBtns = document.querySelectorAll('.filter-btn');
    const productCards = document.querySelectorAll('.product-card');

    searchInputs.forEach((searchInput, index) => {
        if (!searchInput) return;
        const searchPreview = searchPreviews[index];
        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            const term = e.target.value.toLowerCase();

            // RE-ENABLED: Front-end filter for current home page results
            if (typeof filterHomeProducts === 'function' && window.location.pathname === '/') {
                filterHomeProducts(term, getActiveCategory ? getActiveCategory() : 'all');
            }

            // Live search preview
            clearTimeout(searchTimeout);
            if (term.length >= 2) {
                searchTimeout = setTimeout(async () => {
                    try {
                        // Show skeletons while loading
                        if (searchPreview) {
                            searchPreview.style.display = ''; // Clear any inline styles that break CSS
                            searchPreview.classList.add('active');
                            searchPreview.innerHTML = Array(4).fill(0).map(() => window.createSearchSkeletonHtml()).join('');
                        }

                        const limit = searchInput.dataset.limit || 20;
                        const response = await fetch(`/api/search?q=${encodeURIComponent(term)}&limit=${limit}`);
                        const products = await response.json();

                        if (searchPreview) {
                            if (products.length > 0) {
                                searchPreview.innerHTML = products.map(p => {
                                    const hasDiscount = p.discount_price && p.discount_price < p.price;
                                    const priceDisplay = hasDiscount ?
                                        `<span class="preview-price-old" style="text-decoration: line-through; color: #94a3b8; font-size: 0.7rem; margin-right: 5px;">€${parseFloat(p.price).toFixed(2)}</span><span class="preview-price" style="color: #10b981;">€${parseFloat(p.discount_price).toFixed(2)}</span>` :
                                        `<span class="preview-price">€${parseFloat(p.price).toFixed(2)}</span>`;

                                    return `
                                        <a href="/product/${p.id}" class="preview-item">
                                            <div class="preview-image" style="width: 40px; height: 40px; flex-shrink: 0; background: #fff; border-radius: 6px; overflow: hidden; border: 1px solid #f1f5f9;">
                                                <img src="${p.image_url}" alt="${p.name}" style="width: 100%; height: 100%; object-fit: contain; padding: 2px;">
                                            </div>
                                            <div class="preview-info">
                                                <span class="preview-name">${p.name}</span>
                                                ${p.size ? `<span class="preview-size" style="font-size: 0.7rem; color: #64748b; display: block;">${p.size}</span>` : ''}
                                                <div class="preview-price-wrapper" style="font-size: 0.75rem; color: var(--primary); font-weight: 600;">
                                                    ${priceDisplay}
                                                </div>
                                            </div>
                                        </a>
                                    `;
                                }).join('') + `
                                    <a href="/products?q=${encodeURIComponent(term)}" class="preview-item view-all-search">
                                        <span style="width: 100%; text-align: center; color: var(--primary); font-weight: 600; font-size: 0.85rem; padding: 5px 0;">Shiko të gjitha</span>
                                    </a>
                                `;
                            } else {
                                // Show "no results" state instead of leaving skeletons
                                searchPreview.innerHTML = `
                                    <div style="padding: 2rem 1rem; text-align: center; color: #64748b;">
                                        <i class="fas fa-search" style="font-size: 2rem; color: #cbd5e1; margin-bottom: 0.75rem; display: block;"></i>
                                        <p style="margin: 0; font-size: 0.95rem; font-weight: 500;">Nuk u gjet asnjë rezultat për "${term}"</p>
                                    </div>
                                `;
                            }
                            searchPreview.classList.add('active');
                        }
                    } catch (err) {
                        console.error('Search error:', err);
                        if (searchPreview) {
                            searchPreview.innerHTML = `
                                <div style="padding: 1rem; text-align: center; color: #ef4444;">
                                    <p style="margin: 0; font-size: 0.9rem;">Pati një gabim gjatë kërkimit.</p>
                                </div>
                            `;
                            searchPreview.classList.add('active');
                        }
                    }
                }, 300);
            } else if (searchPreview) {
                searchPreview.classList.remove('active');
                searchPreview.style.display = '';
            }
        });

        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault(); // Stop form submission if inside a form
                const term = searchInput.value;
                if (term.length >= 2 && window.location.pathname !== '/') {
                    window.location.href = `/products?q=${encodeURIComponent(term)}`;
                } else if (searchPreview) {
                    searchPreview.classList.remove('active');
                    searchPreview.style.display = '';
                }
            }
        });

        document.addEventListener('click', (e) => {
            if (searchPreview && !searchInput.contains(e.target) && !searchPreview.contains(e.target)) {
                searchPreview.classList.remove('active');
                searchPreview.style.display = '';
            }
        });
    });

    if (filterBtns) {
        filterBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                filterBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const category = btn.getAttribute('data-filter');
                filterHomeProducts(searchInput ? searchInput.value.toLowerCase() : '', category);
            });
        });
    }

    function getActiveCategory() {
        const activeBtn = document.querySelector('.filter-btn.active');
        return activeBtn ? activeBtn.getAttribute('data-filter') : 'all';
    }

    function filterHomeProducts(searchTerm, category) {
        productCards.forEach(card => {
            const h3 = card.querySelector('h3');
            if (!h3) return;
            const name = h3.textContent.toLowerCase();
            const cardCategory = card.getAttribute('data-category');
            const matchesSearch = name.includes(searchTerm);
            const matchesCategory = category === 'all' || cardCategory === category;

            if (matchesSearch && matchesCategory) {
                card.style.display = 'flex';
            } else {
                card.style.display = 'none';
            }
        });
    }

    // --- QUANTITY SELECTOR LOGIC ---
    const qtyInputs = document.querySelectorAll('.quantity-selector');
    qtyInputs.forEach(selector => {
        const input = selector.querySelector('.qty-input');
        const minusBtn = selector.querySelector('.minus');
        const plusBtn = selector.querySelector('.plus');

        if (plusBtn) {
            plusBtn.addEventListener('click', () => {
                let val = parseInt(input.value);
                input.value = val + 1;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            });
        }

        if (minusBtn) {
            minusBtn.addEventListener('click', () => {
                let val = parseInt(input.value);
                if (val > 1) {
                    input.value = val - 1;
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
        }

        if (input) {
            input.addEventListener('focus', () => {
                if (!input.disabled) input.select();
            });

            input.addEventListener('keydown', (e) => {
                if (['.', ',', 'e', 'E', '-'].includes(e.key)) {
                    e.preventDefault();
                    return false;
                }
            });

            input.addEventListener('input', function () {
                // Allow empty input while typing
                if (this.value === '') return;

                let val = parseInt(this.value);
                if (isNaN(val) || val < 1) val = 1;

                // For cart page, we might want to submit automatically after delay
                const form = this.closest('form');
                if (form && (form.matches('[action*="/cart/set/"]') || form.classList.contains('qty-set-form'))) {
                    clearTimeout(this.timeout);
                    this.timeout = setTimeout(() => {
                        this.value = val;
                        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                    }, 800);
                }
            });

            input.addEventListener('blur', function () {
                if (this.value === '' || parseInt(this.value) < 1) {
                    this.value = 1;
                    const form = this.closest('form');
                    if (form) form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                }
            });
        }
    });

    // --- AJAX CART & FORM HANDLERS ---
    document.body.addEventListener('submit', async (e) => {
        if (e.target.id === 'checkout-form') {
            e.preventDefault();
            const result = await Swal.fire({
                title: 'Konfirmo Porosinë',
                text: "A jeni të sigurt që të dhënat janë të sakta?",
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Po, Dërgo',
                cancelButtonText: 'Anulo',
                confirmButtonColor: '#10b981'
            });
            if (result.isConfirmed) e.target.submit();
            return;
        }

        const isAdd = e.target.matches('form[action*="/cart/add/"]');
        const isUpdate = e.target.matches('form[action*="/cart/update/"]');
        const isSet = e.target.matches('form[action*="/cart/set/"]');
        const isRemove = e.target.matches('form[action*="/cart/remove/"]');

        if (!isAdd && !isUpdate && !isRemove && !isSet) return;

        e.preventDefault();
        const form = e.target;

        if (isRemove) {
            const result = await Swal.fire({
                title: 'A jeni i sigurt?',
                text: "Dëshironi ta largoni këtë produkt nga shporta?",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#ef4444',
                cancelButtonColor: '#3b82f6',
                confirmButtonText: 'Po, largoje!',
                cancelButtonText: 'Anulo'
            });
            if (!result.isConfirmed) return;
        }

        let btn = form.querySelector('button[type="submit"]');
        let originalContent = btn ? btn.innerHTML : '';
        let pQtyInput = null;
        let previousQty = null;

        if (btn) {
            btn.disabled = true;
            if (isAdd) btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        }

        if (isUpdate) {
            pQtyInput = form.querySelector('.qty-input');
            if (pQtyInput) previousQty = pQtyInput.value;
            // Removed disabling logic to prevent multi-click lockup
        }

        try {
            const formData = new FormData(form);
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            const data = await response.json();

            if (data.success) {
                if (isAdd) {
                    showToast(data.message, 'success');
                    window.updateGlobalBadges(data);
                } else if (isRemove && data.removed) {
                    const row = form.closest('tr');
                    if (row) {
                        row.style.opacity = '0';
                        setTimeout(() => {
                            row.remove();
                            if (document.querySelectorAll('tbody tr').length === 0) location.reload();
                        }, 300);
                    }
                    showToast(data.message, 'info');

                    // Update Summary Sidebar on Remove
                    const summaryTotal = document.querySelector('.summary-total-price');
                    if (summaryTotal) summaryTotal.textContent = '€' + data.total_price.toFixed(2);

                    const summarySavings = document.querySelector('.summary-total-savings');
                    if (summarySavings && data.total_savings !== undefined) {
                        summarySavings.textContent = '-€' + data.total_savings.toFixed(2);
                        const sRow = summarySavings.closest('.savings-row');
                        if (sRow) sRow.style.display = data.total_savings > 0 ? 'flex' : 'none';
                    }

                    const summaryDelivery = document.querySelector('.summary-delivery-fee');
                    if (summaryDelivery && data.delivery_fee !== undefined) {
                        summaryDelivery.textContent = data.delivery_fee > 0 ? '€' + data.delivery_fee.toFixed(2) : 'Falas';
                    }

                    const grandTotalEls = document.querySelectorAll('.grand-total, .grand-total-amount');
                    grandTotalEls.forEach(el => {
                        const amount = data.grand_total || data.total_price;
                        el.textContent = '€' + amount.toFixed(2);
                    });

                    const oldTotalEl = document.querySelector('.cart-summary h3');
                    if (oldTotalEl) oldTotalEl.textContent = 'Totali: €' + data.total_price.toFixed(2);
                    window.updateGlobalBadges(data);

                } else if (isUpdate || isSet) {
                    const row = form.closest('tr') || form.closest('.cart-item-card');
                    if (row) {
                        const qtyInput = row.querySelector('.qty-input');
                        if (qtyInput) qtyInput.value = data.quantity;

                        // Desktop subtotal
                        const itemTotal = row.querySelector('td:nth-child(4)');
                        if (itemTotal) itemTotal.textContent = '€' + data.item_total.toFixed(2);

                        // Mobile subtotal
                        const mobileItemTotal = row.querySelector('.item-total-mobile');
                        if (mobileItemTotal) mobileItemTotal.textContent = '€' + data.item_total.toFixed(2);

                        // Individual offer helper / savings update
                        const savingsLabels = row.querySelectorAll('.item-savings-label');
                        if (savingsLabels.length) {
                            savingsLabels.forEach(label => {
                                if (data.offer_type === 'multi_buy') {
                                    label.style.display = 'flex';
                                    label.innerHTML = `
                                        <span style="background:#ecfeff; border:1px solid #99f6e4; padding:0.15rem 0.5rem; border-radius:999px; white-space:nowrap;">${data.offer_badge_text || '1+1'}</span>
                                        <span>${data.offer_progress_text || 'Bli më shumë për të fituar një produkt falas.'}</span>
                                    `;
                                    label.style.color = '#0f766e';
                                } else {
                                    const itemSavingsEl = label.querySelector('.savings-amount');
                                    if (itemSavingsEl && data.item_savings !== undefined) {
                                        itemSavingsEl.textContent = '€' + data.item_savings.toFixed(2);
                                        label.style.display = data.item_savings > 0 ? 'block' : 'none';
                                    }
                                }
                            });
                        }

                        const container = row.querySelector('.quantity-selector') || row.querySelector('.quantity-control');
                        if (container) {
                            container.querySelectorAll('.qty-btn').forEach(b => {
                                // Check if it's a minus button
                                const isMinus = b.matches('.minus') || b.querySelector('.fa-minus');
                                b.disabled = isMinus ? data.quantity <= 1 : false;
                            });
                        }
                    }

                    // Update Summary Sidebar
                    const summaryTotal = document.querySelector('.summary-total-price');
                    if (summaryTotal) summaryTotal.textContent = '€' + data.total_price.toFixed(2);

                    const summarySavings = document.querySelector('.summary-total-savings');
                    if (summarySavings && data.total_savings !== undefined) {
                        summarySavings.textContent = '-€' + data.total_savings.toFixed(2);
                        const row = summarySavings.closest('.savings-row');
                        if (row) row.style.display = data.total_savings > 0 ? 'flex' : 'none';
                    }

                    const summaryDelivery = document.querySelector('.summary-delivery-fee');
                    if (summaryDelivery && data.delivery_fee !== undefined) {
                        summaryDelivery.textContent = data.delivery_fee > 0 ? '€' + data.delivery_fee.toFixed(2) : 'Falas';
                    }

                    const totalEl = document.querySelector('.cart-summary h3');
                    if (totalEl) totalEl.textContent = 'Totali: €' + data.total_price.toFixed(2);

                    const grandTotalEls = document.querySelectorAll('.grand-total');
                    grandTotalEls.forEach(el => {
                        const amount = data.grand_total || data.total_price;
                        el.textContent = '€' + amount.toFixed(2);
                    });

                    const sidebarGrandTotal = document.querySelector('.grand-total-amount');
                    if (sidebarGrandTotal) {
                        const amount = data.grand_total || data.total_price;
                        sidebarGrandTotal.textContent = '€' + amount.toFixed(2);
                    }
                    grandTotalEls.forEach(el => {
                        el.textContent = '€' + data.total_price.toFixed(2);
                    });

                    window.updateGlobalBadges(data);
                }
            } else {
                if (isUpdate && pQtyInput) pQtyInput.value = previousQty;
                if (isUpdate) {
                    const row = form.closest('tr');
                    if (row) {
                        const container = row.querySelector('.quantity-selector');
                        if (container) {
                            container.querySelectorAll('button').forEach(b => b.disabled = false);
                            const input = container.querySelector('input');
                            if (input) input.disabled = false;
                        }
                        const minusBtn = row.querySelector('.minus');
                        if (minusBtn && previousQty <= 1) minusBtn.disabled = true;
                    }
                }

                if (response.status === 401 || !data.success) {
                    Swal.fire({
                        title: 'Kërkohet Kyçja!',
                        text: data.message || 'Ju duhet të kyçeni për ta kryer këtë veprim.',
                        icon: 'info',
                        showCancelButton: true,
                        confirmButtonText: 'Kyçu',
                        cancelButtonText: 'Anulo',
                        confirmButtonColor: '#059669'
                    }).then((result) => {
                        if (result.isConfirmed) window.location.href = '/login';
                    });
                } else {
                    showToast(data.message || 'Ndodhi një gabim.', 'danger');
                }
            }
        } catch (error) {
            if (isUpdate && pQtyInput && previousQty !== null) pQtyInput.value = previousQty;
            console.error('Error:', error);
            if (!isRemove) showToast('Ndodhi një gabim.', 'danger');
        } finally {
            if (btn && isAdd) {
                btn.disabled = false;
                btn.innerHTML = originalContent;
            }
        }
    });

    // --- LINK CONFIRMATIONS ---
    document.body.addEventListener('click', async (e) => {
        const trigger = e.target.closest('[data-confirm]');
        if (!trigger) return;

        e.preventDefault();
        const message = trigger.dataset.confirm || "A jeni i sigurt?";
        const href = trigger.getAttribute('href');

        const result = await Swal.fire({
            title: 'Konfirmim',
            text: message,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#ef4444',
            cancelButtonColor: '#6b7280',
            confirmButtonText: 'Po',
            cancelButtonText: 'Jo'
        });

        if (result.isConfirmed && href) {
            window.location.href = href;
        }
    });

    // --- CHECKOUT LOGIN CHECK ---
    const checkoutBtn = document.querySelector('.checkout-btn');
    if (checkoutBtn) {
        checkoutBtn.addEventListener('click', (e) => {
            const isLoggedIn = document.body.dataset.userLoggedIn === 'true';
            if (!isLoggedIn) {
                e.preventDefault();
                Swal.fire({
                    title: 'Kërkohet Hyrja',
                    text: 'Ju lutemi kyçuni ose regjistrohuni për të vazhuduar me pagesën.',
                    icon: 'info',
                    showCancelButton: true,
                    showDenyButton: true,
                    confirmButtonText: 'Kyçu',
                    denyButtonText: 'Regjistrohu',
                    cancelButtonText: 'Anulo',
                    confirmButtonColor: 'var(--primary)',
                    denyButtonColor: 'var(--primary-dark)',
                    reverseButtons: true
                }).then((result) => {
                    if (result.isConfirmed) {
                        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
                    } else if (result.isDenied) {
                        window.location.href = '/register';
                    }
                });
            }
        });
    }

    // --- PRODUCT CARD CLICKABLE ---
    document.querySelectorAll('.product-card').forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', (e) => {
            if (e.target.closest('button') || e.target.closest('a') || e.target.closest('form')) return;
            const detailLink = card.querySelector('a[href*="/product/"]');
            if (detailLink) window.location.href = detailLink.href;
        });
    });

    // --- CAROUSEL SWIPE ---
    initCarouselSwipe();

    // --- HERO CAROUSEL AUTO PLAY ---
    if (document.querySelector('.hero-carousel')) {
        showSlides(slideIndex);
        startSlideTimer();
        const container = document.querySelector('.hero-carousel-container');
        if (container) {
            container.addEventListener('mouseenter', () => clearInterval(slideInterval));
            container.addEventListener('mouseleave', () => startSlideTimer());
        }
    }

    // --- SORT DROPDOWN ---
    const sortTrigger = document.getElementById('sortTrigger');
    const sortMenu = document.getElementById('sortMenu');

    if (sortTrigger && sortMenu) {
        sortTrigger.addEventListener('click', window.toggleSortMenu);

        // Handle Item Click
        sortMenu.addEventListener('click', function (e) {
            const item = e.target.closest('.sort-trigger');
            if (item && !item.id) {
                e.preventDefault();
                const sortVal = item.dataset.sort;
                const labelText = item.innerText.trim();

                const labelSpan = document.getElementById('current-sort-label');
                if (labelSpan) labelSpan.textContent = labelText;

                sortMenu.querySelectorAll('.sort-trigger').forEach(el => el.classList.remove('active'));
                item.classList.add('active');

                const urlParams = new URLSearchParams(window.location.search);
                urlParams.set('sort', sortVal);
                urlParams.set('page', 1);

                window.history.pushState({}, '', `${window.location.pathname}?${urlParams.toString()}`);

                if (typeof updateShop === 'function') {
                    updateShop();
                }

                sortMenu.classList.remove('show');
                sortTrigger.classList.remove('active');
            }
        });

        // Close when clicking outside
        document.addEventListener('click', function (e) {
            if (!sortTrigger.contains(e.target) && !sortMenu.contains(e.target)) {
                sortMenu.classList.remove('show');
                sortTrigger.classList.remove('active');
            }
        });
    }

    // --- SHOP FILTERS ---
    const brandSelect = document.getElementById('brand-select');
    if (brandSelect) brandSelect.addEventListener('change', updateShop);

    const applyPriceBtn = document.getElementById('apply-price-filter');
    if (applyPriceBtn) applyPriceBtn.addEventListener('click', () => { updateShop(); });

    // Init dual-handle price slider
    window.initPriceSlider();

    // Mobile Sidebar Toggle
    const openSidebarBtn = document.getElementById('openSidebar');
    const closeSidebarBtn = document.getElementById('closeSidebar');
    const closeSidebarBtnAlt = document.getElementById('closeSidebarAlt');
    // Using existing sidebar and overlay variables from outer scope if they exist, 
    // but they are already declared at the top of this DOMContentLoaded block.

    if (openSidebarBtn && sidebar && overlay) {
        openSidebarBtn.addEventListener('click', (e) => {
            e.preventDefault();
            window.openShopSidebar();
        });
    }

    if (closeSidebarBtn && sidebar && overlay) {
        closeSidebarBtn.addEventListener('click', (e) => {
            e.preventDefault();
            window.closeShopSidebar();
        });
    }

    if (closeSidebarBtnAlt && sidebar && overlay) {
        closeSidebarBtnAlt.addEventListener('click', (e) => {
            e.preventDefault();
            window.closeShopSidebar();
        });
    }

    if (overlay) {
        overlay.addEventListener('click', window.closeShopSidebar);
    }

    if (sidebar) {
        sidebar.addEventListener('click', (e) => {
            // Prevent clicks inside the sidebar from closing it (if bubbling to overlay)
            e.stopPropagation();
        });
    }

    // Refresh cart & wishlist badges on load
    // Disabled to prevent flickering since server renders correct initial counts
    /*
    if (typeof refreshMiniCart === 'function') {
        refreshMiniCart();
    }
    */
});

// --- GLOBAL FUNCTIONS ---

window.toggleProfileDropdown = function () {
    const dropdown = document.getElementById('desktopProfileDropdown');
    const btn = document.querySelector('.profile-dropdown-btn');
    if (dropdown) {
        dropdown.classList.toggle('active');
        if (btn) btn.classList.toggle('active');
    }
};

// --- CART AJAX & MINI-CART FUNCTIONS ---

window.addToCartAJAX = function (productId, quantity = 1, variantId = null) {
    const formData = new FormData();
    formData.append('quantity', quantity);
    formData.append('csrf_token', document.querySelector('meta[name="csrf-token"]').content);
    if (variantId) formData.append('variant_id', variantId);

    fetch(`/cart/add/${productId}`, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                refreshMiniCart();
                showMiniCart();
            }
        })
        .catch(err => console.error('Error adding to cart:', err));
};

window.buyNow = function (productId, quantity = 1, variantId = null) {
    const formData = new FormData();
    formData.append('quantity', quantity);
    formData.append('csrf_token', document.querySelector('meta[name="csrf-token"]').content);
    if (variantId) formData.append('variant_id', variantId);

    fetch(`/cart/add/${productId}`, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                window.location.href = '/cart/checkout';
            }
        })
        .catch(err => console.error('Error in Buy Now:', err));
};

window.toggleMiniCart = function (e) {
    if (e) e.preventDefault();
    const miniCart = document.getElementById('miniCart');
    if (miniCart) {
        miniCart.classList.toggle('active');
        if (miniCart.classList.contains('active')) {
            refreshMiniCart();
        }
    }
};

window.showMiniCart = function () {
    const miniCart = document.getElementById('miniCart');
    if (miniCart) {
        miniCart.classList.add('active');
        // If it was auto-opened (after adding to cart), auto-close it
        setTimeout(() => {
            // Only auto-hide if it's still active (might have been toggled off manually)
            if (miniCart.classList.contains('active')) {
                miniCart.classList.remove('active');
            }
        }, 2500);
    }
};

window.updateGlobalBadges = function (data) {
    if (!data) return;

    // 1. Update Cart Badges
    if (data.cart_count !== undefined) {
        const cartBadges = document.querySelectorAll('.cart-badge, .mobile-cart-badge, .cart-count-badge, .items-count-badge-mobile');
        cartBadges.forEach(badge => {
            if (badge.classList.contains('items-count-badge-mobile')) {
                badge.textContent = `${data.cart_count} produkt(e)`;
            } else {
                badge.textContent = data.cart_count;
            }
            if (data.cart_count > 0) {
                badge.classList.remove('d-none');
                badge.style.setProperty('display', 'flex', 'important');
            } else {
                badge.classList.add('d-none');
                badge.style.setProperty('display', 'none', 'important');
            }
        });

        const countText = document.querySelector('.items-count-text');
        if (countText) countText.textContent = `${data.cart_count} produkt(e)`;
    }

    // 2. Update Wishlist Badges
    const wishCount = data.wishlist_count !== undefined ? data.wishlist_count : (data.count !== undefined ? data.count : undefined);
    if (wishCount !== undefined) {
        const wishBadges = document.querySelectorAll('.wishlist-count, .cart-badge-wish');
        wishBadges.forEach(badge => {
            badge.textContent = wishCount;
            if (wishCount > 0) {
                badge.classList.remove('d-none');
                badge.style.setProperty('display', 'flex', 'important');
            } else {
                badge.classList.add('d-none');
                badge.style.setProperty('display', 'none', 'important');
            }
        });
    }

    // 3. Update Mini Cart Footer Button Total
    if (data.total_price !== undefined) {
        const footerBtn = document.querySelector('.btn-go-to-cart');
        if (footerBtn) {
            footerBtn.innerHTML = `SHKO NË SHPORTË (${parseFloat(data.total_price).toFixed(2)} €)`;
        }
    }
};

window.refreshMiniCart = function () {
    fetch('/cart/mini-cart-data')
        .then(res => res.json())
        .then(data => {
            // Use the unified update function
            window.updateGlobalBadges(data);

            // Update Desktop Mini Cart
            const desktopContainer = document.querySelector('.mini-cart-items');
            if (desktopContainer) {
                if (data.cart_items.length === 0) {
                    desktopContainer.innerHTML = `
                    <div class="empty-mini-cart">
                        <i class="fas fa-shopping-basket fa-3x mb-3"></i>
                        <p>Shporta juaj është boshe.</p>
                    </div>`;
                } else {
                    let html = '';
                    data.cart_items.forEach(item => {
                        const price = item.discount_price || item.price;
                        const productUrl = `/product/${item._id}`;
                        html += `
                    <div class="mini-cart-item" data-id="${item._id}" onclick="window.location.href='${productUrl}';">
                        <a href="${productUrl}" class="mini-cart-img-wrapper" onclick="event.stopPropagation()">
                            <img src="${window.cldUrl(item.image_url, 120)}" alt="${item.name}" class="mini-cart-img">
                        </a>
                        <div class="mini-cart-info">
                            <a href="${productUrl}" class="mini-item-name" onclick="event.stopPropagation()">${item.name}</a>
                            <div class="mini-item-meta">
                                <span class="mini-item-price">€${parseFloat(price).toFixed(2)}</span>
                                <div class="mini-qty-control" onclick="event.stopPropagation()">
                                    <button class="qty-control-btn minus" onclick="updateMiniQty(event, '${item._id}', 'decrease')">
                                        <i class="fas fa-minus"></i>
                                    </button>
                                    <span class="qty-val">${item.quantity}</span>
                                    <button class="qty-control-btn plus" onclick="updateMiniQty(event, '${item._id}', 'increase')">
                                        <i class="fas fa-plus"></i>
                                    </button>
                                </div>
                            </div>
                            ${item.offer_type === 'multi_buy' ? `
                            <div class="mini-item-offer-hint" style="margin-top: 0.35rem; color: #0f766e; font-size: 0.78rem; font-weight: 600; display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
                                <span style="background:#ecfeff; border:1px solid #99f6e4; padding:0.15rem 0.5rem; border-radius:999px; white-space:nowrap;">${item.offer_badge_text || '1+1'}</span>
                                <span>${item.offer_detail_text || 'Merr 1 produkt falas kur blen këtë ofertë.'}</span>
                            </div>` : ''}
                        </div>
                        <button class="remove-item-btn" onclick="updateMiniQty(event, '${item._id}', 'remove')" title="Hiqe">
                            <i class="far fa-trash-alt"></i>
                        </button>
                    </div>`;
                    });
                    desktopContainer.innerHTML = html;
                }
            }

            // Update Mobile Modal Cart
            const mobileContainer = document.querySelector('.mobile-cart-items-list');
            const mobileHeader = document.querySelector('.mobile-mini-cart-header');

            if (mobileContainer) {
                if (data.cart_items.length === 0) {
                    // Update header (hide clear cart link)
                    if (mobileHeader) mobileHeader.innerHTML = '';

                    mobileContainer.innerHTML = `
                    <div class="empty-cart-state-mobile">
                        <div class="icon-circle">
                            <i class="fas fa-shopping-basket"></i>
                        </div>
                        <h4>Shporta juaj është boshe</h4>
                        <p>Ju nuk keni shtuar asnjë produkt në shportë akoma.</p>
                        <button class="btn-primary-mobile" onclick="closeCartModal()">Fillo Blerjen</button>
                    </div>`;
                } else {
                    // Update header
                    if (mobileHeader) {
                        mobileHeader.innerHTML = `
                        <a href="#" class="clear-cart-link-mobile" onclick="clearCart(event)">
                            <i class="fas fa-trash-alt"></i> Pastro Shportën
                        </a>`;
                    }

                    let html = '';
                    data.cart_items.forEach(item => {
                        const price = item.discount_price || item.price;
                        const productUrl = `/product/${item._id}`;
                        html += `
                    <div class="mobile-mini-cart-item" data-id="${item._id}" onclick="window.location.href='${productUrl}';">
                        <div class="mobile-mini-cart-img">
                            <img src="${window.cldUrl(item.image_url, 120)}" alt="${item.name}">
                        </div>
                        <div class="mobile-mini-cart-info">
                            <p class="name">${item.name}</p>
                            <p class="price">€${parseFloat(price).toFixed(2)}</p>
                            ${item.offer_type === 'multi_buy' ? `
                            <p class="offer-hint" style="margin: 0.2rem 0 0; color: #0f766e; font-size: 0.72rem; font-weight: 600; line-height: 1.3;">
                                <span style="background:#ecfeff; border:1px solid #99f6e4; padding:0.12rem 0.45rem; border-radius:999px; margin-right:0.35rem; display:inline-block;">${item.offer_badge_text || '1+1'}</span>
                                ${item.offer_detail_text || 'Merr 1 produkt falas kur blen këtë ofertë.'}
                            </p>` : ''}
                            <div class="qty-control-mobile" onclick="event.stopPropagation()">
                                <button class="qty-btn" onclick="updateMiniQty(event, '${item._id}', 'decrease')">-</button>
                                <span class="qty-val">${item.quantity}</span>
                                <button class="qty-btn" onclick="updateMiniQty(event, '${item._id}', 'increase')">+</button>
                            </div>
                        </div>
                        <button class="remove-btn" onclick="updateMiniQty(event, '${item._id}', 'remove')">
                            <i class="far fa-trash-alt"></i>
                        </button>
                    </div>`;
                    });
                    mobileContainer.innerHTML = html;
                }
            }
        });
};

window.updateMiniQty = function (event, productId, action) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    // Support both desktop mini-cart and mobile modal cart
    const itemRows = document.querySelectorAll(`.mini-cart-item[data-id="${productId}"], .mobile-mini-cart-item[data-id="${productId}"]`);

    const formData = new FormData();
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    formData.append('csrf_token', csrfToken);

    fetch(`/cart/update/${productId}/${action}`, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                window.updateGlobalBadges(data);

                itemRows.forEach(row => {
                    if (action === 'remove') {
                        row.remove();
                    } else {
                        const qtySpan = row.querySelector('.qty-val');
                        if (qtySpan) qtySpan.textContent = data.quantity;
                    }
                });

                // If cart is empty now, refresh the whole UI to show empty state
                if (data.cart_count === 0) {
                    window.refreshMiniCart();
                }

                // Update totals if they exist
                const footers = document.querySelectorAll('.mini-cart-footer, .modal-footer-cart');
                footers.forEach(footer => {
                    const totalSpan = footer.querySelector('.btn-go-to-cart, .total-price, .grand-total');
                    if (totalSpan) {
                        if (totalSpan.classList.contains('btn-go-to-cart')) {
                            totalSpan.textContent = `SHKO NË SHPORTË (${data.cart_total.toFixed(2)} €)`;
                        } else if (totalSpan.classList.contains('total-price') && !totalSpan.closest('.modal-footer-cart')) {
                            totalSpan.textContent = `€${data.cart_total.toFixed(2)}`;
                        } else if (footer.classList.contains('modal-footer-cart')) {
                            // Handle the new detailed modal footer
                            const subtotalEl = footer.querySelector('div:first-child > div:first-child span:last-child');
                            const deliveryEl = footer.querySelector('div:first-child > div:nth-child(2) span:last-child');
                            const savingsEl = footer.querySelector('div:first-child > div:nth-child(3) span:last-child');
                            const grandTotalEl = footer.querySelector('.grand-total') || footer.querySelector('div:first-child > div:last-child span:last-child');

                            if (subtotalEl) subtotalEl.textContent = `€${data.cart_total.toFixed(2)}`;
                            if (deliveryEl) deliveryEl.textContent = data.delivery_fee > 0 ? `€${data.delivery_fee.toFixed(2)}` : 'Falas';
                            if (grandTotalEl) grandTotalEl.textContent = `€${data.grand_total.toFixed(2)}`;
                        }
                    }
                });

                if (data.cart_count === 0) {
                    // Desktop
                    const desktopContainer = document.querySelector('.mini-cart-items');
                    if (desktopContainer) {
                        desktopContainer.innerHTML = `
                        <div class="empty-mini-cart">
                            <i class="fas fa-shopping-basket fa-3x mb-3"></i>
                            <p>Shporta juaj është boshe.</p>
                        </div>`;
                    }
                    // Mobile
                    const mobileContainer = document.querySelector('.mobile-cart-items-list');
                    if (mobileContainer) {
                        mobileContainer.innerHTML = `
                        <div class="empty-cart-state-mobile">
                            <div class="icon-circle"><i class="fas fa-shopping-basket"></i></div>
                            <h4>Shporta juaj është boshe</h4>
                            <p>Ju nuk keni shtuar asnjë produkt në shportë akoma.</p>
                            <button class="btn-primary-mobile" onclick="closeCartModal()">Fillo Blerjen</button>
                        </div>`;
                    }
                    // Remove footer
                    const mobileFooter = document.querySelector('.modal-footer-cart');
                    if (mobileFooter) mobileFooter.remove();
                }

                if (action === 'remove' || data.cart_count === 0) {
                    window.refreshMiniCart();
                }

                if (window.location.pathname === '/cart/') {
                    window.location.reload();
                }
            }
        })
        .catch(err => {
            console.error('Error updating mini cart:', err);
            window.refreshMiniCart();
        });
};

window.clearCart = function (event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }

    // Improved confirmation dialog
    const confirmed = window.confirm('Kujdes: A jeni i sigurt që dëshironi të fshini të gjitha produktet nga shporta? Ky veprim nuk mund të kthehet mbrapsht.');
    if (!confirmed) return;

    const formData = new FormData();
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
    formData.append('csrf_token', csrfToken);

    fetch('/cart/clear', {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                refreshMiniCart();
                if (window.location.pathname === '/cart/') {
                    window.location.reload();
                }
            }
        })
        .catch(err => console.error('Error clearing cart:', err));
};

window.openCategoriesModal = function () {
    window.closeCartModal();
    window.closeProfileModal();
    const modal = document.getElementById('mobile-categories-modal');
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        document.body.classList.add('modal-open');
    }
};

window.closeCategoriesModal = function () {
    const modal = document.getElementById('mobile-categories-modal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
    }
};

window.openCartModal = function () {
    window.closeCategoriesModal();
    window.closeProfileModal();
    const modal = document.getElementById('mobile-cart-modal');
    if (modal) {
        // Refresh cart data whenever opening the modal to ensure it's not empty/stale
        if (typeof window.refreshMiniCart === 'function') {
            window.refreshMiniCart();
        }
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        document.body.classList.add('modal-open');
    }
};

window.closeCartModal = function () {
    const modal = document.getElementById('mobile-cart-modal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
    }
};

// --- FIX FOR BACK BUTTON CACHE (bfcache) ---
window.addEventListener('pageshow', (event) => {
    // If the page is loaded from cache (e.g. back button), force close all modals
    if (event.persisted) {
        if (typeof window.closeCategoriesModal === 'function') window.closeCategoriesModal();
        if (typeof window.closeCartModal === 'function') window.closeCartModal();
        if (typeof window.closeProfileModal === 'function') window.closeProfileModal();
    }
});

// Auto-close modals when any link inside them is clicked
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.full-screen-modal a').forEach(link => {
        link.addEventListener('click', () => {
            const modal = link.closest('.full-screen-modal');
            if (modal) {
                modal.classList.remove('active');
                document.body.style.overflow = '';
            }
        });
    });
});

window.openProfileModal = function () {
    window.closeCategoriesModal();
    window.closeCartModal();
    const modal = document.getElementById('mobile-profile-modal');
    if (modal) {
        modal.classList.add('active');
        document.body.style.overflow = 'hidden';
        document.body.classList.add('modal-open');
    }
};

window.closeProfileModal = function () {
    const modal = document.getElementById('mobile-profile-modal');
    if (modal) {
        modal.classList.remove('active');
        document.body.style.overflow = '';
        document.body.classList.remove('modal-open');
    }
};

window.confirmDelete = function (formElement) {
    Swal.fire({
        title: 'A jeni i sigurt?',
        text: "Ky veprim nuk mund të kthehet mbrapa!",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#e11d48',
        cancelButtonColor: '#64748b',
        confirmButtonText: 'Po, fshije!',
        cancelButtonText: 'Anulo'
    }).then((result) => {
        if (result.isConfirmed) formElement.submit();
    });
    return false;
};

window.showToast = function (message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-v4 toast-${type}`;

    let icon = 'fa-check-circle';
    if (type === 'error' || type === 'danger') icon = 'fa-exclamation-circle';
    else if (type === 'warning') icon = 'fa-exclamation-triangle';
    else if (type === 'info') icon = 'fa-info-circle';

    toast.innerHTML = `
        <div class="toast-icon-v4">
            <i class="fas ${icon}"></i>
        </div>
        <div class="toast-content-v4">
            <span class="toast-message-v4">${message}</span>
        </div>
        <button class="toast-close-v4" onclick="this.parentElement.classList.add('hide'); setTimeout(() => this.parentElement.remove(), 400)">
            <i class="fas fa-times"></i>
        </button>
        <div class="toast-progress-v4"></div>
    `;

    container.appendChild(toast);

    // Auto-remove after 4 seconds
    const timeout = setTimeout(() => {
        toast.classList.add('hide');
        setTimeout(() => toast.remove(), 400);
    }, 4000);

    // Pause on hover
    toast.onmouseenter = () => {
        toast.querySelector('.toast-progress-v4').style.animationPlayState = 'paused';
    };
};

window.toggleFavorite = async function (btn, productId) {
    if (!productId) return;
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    try {
        const response = await fetch(`/product/favorite/${productId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken }
        });
        const data = await response.json();
        if (data.success) {
            const icon = btn.querySelector('i');

            // Use the unified global update function
            window.updateGlobalBadges({
                wishlist_count: data.wishlist_count !== undefined ? data.wishlist_count : data.count
            });

            if (data.action === 'added') {
                btn.classList.add('active');
                if (icon) { icon.classList.replace('far', 'fas'); }
                showToast('Produkti u shtua në të preferuarat!', 'success');
            } else {
                btn.classList.remove('active');
                if (icon) { icon.classList.replace('fas', 'far'); }
                showToast('Produkti u largua nga të preferuarat', 'info');

                // --- WISHLIST DYNAMIC EMPTY STATE ---
                if (window.location.pathname.includes('/wishlist')) {
                    const card = btn.closest('.product-card');
                    if (card) {
                        card.style.opacity = '0';
                        setTimeout(() => {
                            card.remove();
                            const remaining = document.querySelectorAll('.product-grid-v2 .product-card').length;
                            if (remaining === 0) {
                                const container = document.querySelector('.wishlist-section .container');
                                if (container) {
                                    container.innerHTML = `
                                        <div class="empty-state-card text-center py-5">
                                            <div class="empty-icon mb-4"><i class="far fa-heart fa-3x"></i></div>
                                            <h3>Nuk keni asnjë produkt të preferuar ende</h3>
                                            <p class="text-muted mb-4">Eksploroni produktet tona dhe shtoni ato që ju pëlqejnë këtu.</p>
                                            <a href="/products" class="btn btn-primary px-5 btn-lg">Eksploro Dyqanin</a>
                                        </div>
                                    `;
                                }
                            }
                        }, 300);
                    }
                }
            }
        } else {
            showToast('Duhet të jeni të kyçur për të ruajtur produktet.', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showToast('Ndodhi një gabim.', 'error');
    }
};

function initCarouselSwipe() {
    const containers = document.querySelectorAll('.carousel-container');
    containers.forEach(container => {
        let touchstartX = 0;
        let touchendX = 0;

        container.addEventListener('touchstart', e => {
            touchstartX = e.changedTouches[0].clientX;
        }, { passive: true });

        container.addEventListener('touchend', e => {
            touchendX = e.changedTouches[0].clientX;
            const dx = touchendX - touchstartX;
            if (Math.abs(dx) > 50) {
                moveCarousel(null, container, dx < 0 ? 1 : -1);
            }
        }, { passive: true });
    });
}

function moveCarousel(event, btnOrTrack, direction) {
    if (event && event.preventDefault) { event.preventDefault(); event.stopPropagation(); }
    const container = btnOrTrack.closest('.carousel-container');
    if (!container) return;
    const track = container.querySelector('.carousel-track');
    const images = track ? track.querySelectorAll('img') : [];
    if (!images.length) return;
    let currentIndex = parseInt(container.getAttribute('data-index') || '0');
    currentIndex += direction;
    if (currentIndex < 0) currentIndex = images.length - 1;
    if (currentIndex >= images.length) currentIndex = 0;
    goToSlide(container, currentIndex);
}

function goToSlide(container, index) {
    const track = container.querySelector('.carousel-track');
    const dots = container.querySelectorAll('.indicator-dot');
    const thumbs = container.parentElement ? container.parentElement.querySelectorAll('.thumbnail') : null;
    container.setAttribute('data-index', index);
    if (track) track.style.transform = `translateX(-${index * 100}%)`;
    if (dots) dots.forEach((dot, i) => dot.classList.toggle('active', i === index));
    if (thumbs) {
        thumbs.forEach((thumb, i) => {
            thumb.style.borderColor = i === index ? 'var(--primary)' : 'transparent';
            thumb.style.opacity = i === index ? '1' : '0.7';
        });
    }
}

let slideIndex = 1;
let slideInterval;

function startSlideTimer() {
    clearInterval(slideInterval);
    slideInterval = setInterval(() => plusSlides(1), 5000);
}

window.plusSlides = function (n) { showSlides(slideIndex += n); }
window.currentSlide = function (n) { showSlides(slideIndex = n); }

function showSlides(n) {
    let i;
    const slides = document.getElementsByClassName("hero-slide");
    const dots = document.getElementsByClassName("hero-dot");
    if (!slides || slides.length === 0) return;
    if (n > slides.length) slideIndex = 1;
    if (n < 1) slideIndex = slides.length;
    for (i = 0; i < slides.length; i++) slides[i].classList.remove("active");
    for (i = 0; i < dots.length; i++) dots[i].classList.remove("active");
    slides[slideIndex - 1].classList.add("active");
    if (dots.length >= slideIndex) dots[slideIndex - 1].classList.add("active");
    startSlideTimer();
}

function initHeroSwipe() {
    const hero = document.querySelector('.hero-carousel-container');
    if (!hero) return;

    let touchstartX = 0;
    let touchendX = 0;

    hero.addEventListener('touchstart', e => {
        touchstartX = e.changedTouches[0].clientX;
    }, { passive: true });

    hero.addEventListener('touchend', e => {
        touchendX = e.changedTouches[0].clientX;
        const dx = touchendX - touchstartX;
        if (Math.abs(dx) > 50) {
            plusSlides(dx < 0 ? 1 : -1);
        }
    }, { passive: true });
}

document.addEventListener('DOMContentLoaded', () => {
    initHeroSwipe();
});

function openQuickView(element) {
    const card = element.closest('.product-card');
    if (!card) return;
    const modal = document.getElementById('quickViewModal');
    if (!modal) return;

    document.getElementById('qv-image').src = card.getAttribute('data-img') || '';
    document.getElementById('qv-title').innerText = card.getAttribute('data-name') || '';
    document.getElementById('qv-price').innerText = (card.getAttribute('data-price') || '0') + ' €';
    document.getElementById('qv-description').innerText = card.getAttribute('data-desc') || '';

    const detailsBtn = modal.querySelector('a.btn-outline, a[href]');
    if (detailsBtn) detailsBtn.href = card.getAttribute('data-url') || '#';

    const addBtn = document.getElementById('qv-add-btn');
    if (addBtn) addBtn.onclick = () => addToCartQuickView(card.getAttribute('data-id'));

    modal.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeQuickView() {
    const modal = document.getElementById('quickViewModal');
    if (modal) { modal.classList.remove('show'); document.body.style.overflow = ''; }
}

window.onclick = function (event) {
    const modal = document.getElementById('quickViewModal');
    if (event.target == modal) closeQuickView();
};

// --- PRODUCT CAROUSEL SCROLL ---
window.scrollCarousel = function (btn, direction) {
    const wrapper = btn.closest('.product-carousel-wrapper');
    if (!wrapper) return;
    const carousel = wrapper.querySelector('.product-carousel');
    if (!carousel) return;

    const scrollAmount = carousel.clientWidth * 0.8;
    const maxScroll = carousel.scrollWidth - carousel.clientWidth;
    let target = carousel.scrollLeft + (direction * scrollAmount);

    // Clamp values to prevent overscrolling beyond the first/last product
    if (target < 0) target = 0;
    if (target > maxScroll) target = maxScroll;

    carousel.scrollTo({
        left: target,
        behavior: 'smooth'
    });
};

// Initial check for carousel buttons visibility
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.product-carousel').forEach(carousel => {
        const updateButtons = () => {
            const wrapper = carousel.closest('.product-carousel-wrapper');
            if (!wrapper) return;
            const prevBtn = wrapper.querySelector('.scroll-btn.prev');
            const nextBtn = wrapper.querySelector('.scroll-btn.next');
            const maxScroll = carousel.scrollWidth - carousel.clientWidth;

            if (prevBtn) prevBtn.style.opacity = carousel.scrollLeft <= 5 ? '0' : '1';
            if (prevBtn) prevBtn.style.pointerEvents = carousel.scrollLeft <= 5 ? 'none' : 'auto';
            if (nextBtn) nextBtn.style.opacity = carousel.scrollLeft >= maxScroll - 5 ? '0' : '1';
            if (nextBtn) nextBtn.style.pointerEvents = carousel.scrollLeft >= maxScroll - 5 ? 'none' : 'auto';
        };

        carousel.addEventListener('scroll', updateButtons);
        // Initial state
        setTimeout(updateButtons, 500);
        window.addEventListener('resize', updateButtons);
    });
});

function addToCartQuickView(productId) { addToCart(productId); closeQuickView(); }

function addToCart(productId) {
    if (!productId) return;
    const btns = document.querySelectorAll(`button[onclick="addToCart('${productId}')"]`);
    btns.forEach(btn => { btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; btn.disabled = true; });

    fetch(`/cart/add/${productId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Use the unified global update function
                window.updateGlobalBadges({
                    cart_count: data.cart_count,
                    wishlist_count: data.wishlist_count,
                    total_price: data.total_price || data.grand_total
                });

                // Refresh modal lists
                if (typeof window.refreshMiniCart === 'function') {
                    window.refreshMiniCart();
                }

                btns.forEach(btn => {
                    btn.innerHTML = '<i class="fas fa-check"></i>';
                    btn.style.background = '#10b981';
                    setTimeout(() => {
                        btn.innerHTML = '<i class="fas fa-shopping-basket"></i>';
                        btn.disabled = false;
                        btn.style.background = '';
                    }, 1500);
                });
            }
        })
        .catch(error => {
            console.error('Error:', error);
            btns.forEach(btn => {
                btn.innerHTML = '<i class="fas fa-exclamation"></i>';
                setTimeout(() => { btn.innerHTML = '<i class="fas fa-shopping-basket"></i>'; btn.disabled = false; }, 2000);
            });
        });
}


// Global Refresh to fix any badge visibility blockers removed as it causes delay
// Relying on server-side rendering for initial load.

// Global Refresh to fix any badge visibility blockers removed as it causes delay
// Relying on server-side rendering for initial load.

document.addEventListener('DOMContentLoaded', () => {
    // Global Refresh to fix any badge visibility blockers
    if (typeof window.refreshMiniCart === 'function') {
        // Delay slightly to ensure server-rendered view is ready
        setTimeout(() => window.refreshMiniCart(), 500);
    }
});

window.filterBrandList = function() {
    const input = document.getElementById('brandSearchInput');
    if (!input) return;
    const filter = input.value.toUpperCase();
    const ul = document.querySelector('.brand-list');
    if (!ul) return;
    const li = ul.getElementsByTagName('li');
    for (let i = 0; i < li.length; i++) {
        const a = li[i].getElementsByTagName('a')[0];
        if (a) {
            const txtValue = a.textContent || a.innerText;
            if (txtValue.trim().toUpperCase() === 'TË GJITHA') {
                li[i].style.display = '';
                continue;
            }
            if (txtValue.toUpperCase().indexOf(filter) > -1) {
                li[i].style.display = '';
            } else {
                li[i].style.display = 'none';
            }
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Pre-fill search inputs if 'search' is in URL so user knows they are restricting view
    const params = new URLSearchParams(window.location.search);
    const searchVal = params.get('search');
    if (searchVal) {
        const desktopSearch = document.getElementById('productSearch');
        const mobileSearch = document.getElementById('productSearchMobile');
        const adminSearch = document.getElementById('adminOrderSearch');
        if (desktopSearch) desktopSearch.value = searchVal;
        if (mobileSearch) mobileSearch.value = searchVal;
        if (adminSearch) adminSearch.value = searchVal;
    }
});

// --- AI Chatbot Widget ---
const chatbotState = {
    openedOnce: false,
    busy: false,
    currentConversationId: null,
    conversations: [],
    showConversationList: false
};

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function getChatbotElements() {
    return {
        panel: document.getElementById('chatbotPanel'),
        messages: document.getElementById('chatbotMessages'),
        form: document.getElementById('chatbotForm'),
        input: document.getElementById('chatbotInput'),
        sendBtn: document.getElementById('chatbotSendBtn'),
    };
}

function buildChatbotChip(text, href = null, extraClass = '') {
    const label = escapeHtml(text);
    if (href) {
        return `<a class="chatbot-chip ${extraClass}" href="${escapeHtml(href)}">${label}</a>`;
    }
    return `<button type="button" class="chatbot-chip ${extraClass}">${label}</button>`;
}

function buildChatbotAttachments(quickReplies = [], products = [], seeMoreUrl = '') {
    const productStrip = Array.isArray(products) && products.length
        ? `
            <div class="chatbot-product-strip" role="list" aria-label="Produktet e sugjeruara">
                ${products.slice(0, 5).map((product) => `
                    <a class="chatbot-product-card" role="listitem" href="/product/${escapeHtml(product.id || '')}">
                        <img class="chatbot-product-image" src="${escapeHtml(window.cldUrl(product.image_url, 200) || '')}" alt="${escapeHtml(product.name || 'Produkt')}">
                        <div class="chatbot-product-meta">
                            <div class="chatbot-product-name">${escapeHtml(product.name || 'Produkt')}</div>
                            <div class="chatbot-product-subtitle">${escapeHtml([product.brand, product.subcategory || product.category, product.size].filter(Boolean).join(' • '))}</div>
                            <div class="chatbot-product-price">€${parseFloat(product.discount_price || product.price || 0).toFixed(2)}</div>
                        </div>
                    </a>
                `).join('')}
                ${seeMoreUrl ? `<a class="chatbot-chip chatbot-chip-see-more" href="${escapeHtml(seeMoreUrl)}">Shiko më shumë</a>` : ''}
            </div>
        `
        : '';

    const quickReplyRow = Array.isArray(quickReplies) && quickReplies.length
        ? `
            <div class="chatbot-chip-row">
                ${quickReplies.slice(0, 8).map((reply) => buildChatbotChip(reply)).join('')}
                ${seeMoreUrl ? buildChatbotChip('Shiko të gjitha', seeMoreUrl, 'chatbot-chip-see-more') : ''}
            </div>
        `
        : '';

    if (!productStrip && !quickReplyRow) return '';

    return `
        <div class="chatbot-attachments">
            <button type="button" class="chatbot-attachments-close" aria-label="Mbyll sugjerimet">
                <i class="fas fa-times"></i>
            </button>
            ${productStrip}
            ${quickReplyRow}
        </div>
    `;
}

function normalizeAssistantMessage(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) {
        return value
            .map((part) => {
                if (typeof part === 'string') return part;
                if (part && typeof part === 'object' && typeof part.text === 'string') return part.text;
                return '';
            })
            .filter(Boolean)
            .join('\n');
    }
    if (value && typeof value === 'object') {
        if (typeof value.text === 'string') return value.text;
        try {
            return JSON.stringify(value);
        } catch (_) {
            return '';
        }
    }
    return '';
}

function formatChatbotText(text) {
    const safeText = escapeHtml(String(text || ''));
    // Keep line breaks from LLM responses so long answers are readable end-to-end.
    return safeText.replace(/\n/g, '<br>');
}

function showAttachments(html) {
    const container = document.getElementById('chatbotAttachments');
    if (!container) return;
    container.innerHTML = html || '';
    container.classList.remove('collapsed');
    // keep focus on input and ensure attachments are visible
    const { input, messages } = getChatbotElements();
    if (messages) messages.scrollTop = messages.scrollHeight;
    if (input) input.focus();
}

function addChatbotMessage(role, text, attachmentsHtml = '') {
    const { messages } = getChatbotElements();
    if (!messages) return null;

    const row = document.createElement('div');
    row.className = `chatbot-message ${role}`;
    row.innerHTML = `
        <div class="message-bubble">${formatChatbotText(text)}</div>
    `;
    messages.appendChild(row);
    messages.scrollTop = messages.scrollHeight;
    
    // Hide welcome screen if visible
    const welcome = document.getElementById('chatbotWelcome');
    if (welcome) welcome.style.display = 'none';
    
    return row;
}

async function sendChatbotMessage(messageOverride = null) {
    const { input, sendBtn } = getChatbotElements();
    const typingIndicator = document.getElementById('typingIndicator');
    if (!input) return;

    const message = String(messageOverride !== null ? messageOverride : input.value).trim();
    if (!message || chatbotState.busy) return;

    if (!chatbotState.openedOnce) {
        toggleChatbot(true);
    }

    // Hide clear button
    const clearBtn = document.getElementById('clearBtn');
    if (clearBtn) clearBtn.style.display = 'none';

    addChatbotMessage('user', message);
    input.value = '';
    if (sendBtn) sendBtn.disabled = true;
    chatbotState.busy = true;

    // Show typing indicator
    if (typingIndicator) typingIndicator.style.display = 'flex';

    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

        const response = await fetch('/api/chatbot', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({
                message: message,
                conversation_id: chatbotState.currentConversationId
            })
        });

        const data = await response.json();
        
        // Hide typing indicator
        if (typingIndicator) typingIndicator.style.display = 'none';

        if (!data.success) {
            addChatbotMessage('bot', 'Nuk munda ta përpunoj kërkesën. Provoni sërish.');
            return;
        }

        // Update current conversation ID if this was a new conversation
        if (data.conversation_id && data.conversation_id !== chatbotState.currentConversationId) {
            chatbotState.currentConversationId = data.conversation_id;
            await loadConversations(); // Refresh conversation list
        }

        const assistantMessage = normalizeAssistantMessage(data.message) || 'Ja disa opsione që mund t\'ju ndihmojnë.';
        addChatbotMessage('bot', assistantMessage);
        showAttachments(buildChatbotAttachments(data.quick_replies || [], data.products || [], data.see_more_url || ''));
    } catch (error) {
        console.error('Chatbot error:', error);
        if (typingIndicator) typingIndicator.style.display = 'none';
        addChatbotMessage('bot', 'Ndodhi një gabim gjatë kërkimit. Ju lutem provoni përsëri.');
    } finally {
        chatbotState.busy = false;
        if (sendBtn) sendBtn.disabled = false;
    }
}

// Conversation management functions
window.loadConversations = async function() {
    try {
        const response = await fetch('/api/conversations');
        const data = await response.json();
        chatbotState.conversations = data.conversations || [];
        updateConversationUI();
    } catch (error) {
        console.error('Error loading conversations:', error);
    }
}

window.createNewConversation = async function(title = 'Biseda e re') {
    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

        const response = await fetch('/api/conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ title })
        });

        const data = await response.json();
        if (data.success) {
            chatbotState.currentConversationId = data.conversation._id;
            await loadConversations();
            await loadConversationMessages(data.conversation._id);
            return data.conversation;
        }
    } catch (error) {
        console.error('Error creating conversation:', error);
    }
    return null;
}

window.loadConversationMessages = async function(conversationId) {
    try {
        const response = await fetch(`/api/conversations/${conversationId}`);
        const data = await response.json();
        
        if (data.conversation) {
            const { messages } = getChatbotElements();
            if (messages) {
                messages.innerHTML = ''; // Clear current messages
                
                // Load conversation history
                data.conversation.messages.forEach(msg => {
                    addChatbotMessage(msg.role, msg.content);
                });
                
                // Scroll to bottom
                messages.scrollTop = messages.scrollHeight;
            }
        }
    } catch (error) {
        console.error('Error loading conversation messages:', error);
    }
}

window.switchToConversation = async function(conversationId) {
    chatbotState.currentConversationId = conversationId;
    await loadConversationMessages(conversationId);
    updateConversationUI();
}

window.deleteConversation = async function(conversationId) {
    if (!confirm('A jeni i sigurt që doni të fshini këtë bisedë?')) return;
    
    try {
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

        const response = await fetch(`/api/conversations/${conversationId}`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': csrfToken
            }
        });

        const data = await response.json();
        if (data.success) {
            if (chatbotState.currentConversationId === conversationId) {
                chatbotState.currentConversationId = null;
                const { messages } = getChatbotElements();
                if (messages) messages.innerHTML = '';
            }
            await loadConversations();
        }
    } catch (error) {
        console.error('Error deleting conversation:', error);
    }
}

function updateConversationUI() {
    const conversationList = document.getElementById('conversationList');
    if (!conversationList) return;

    if (chatbotState.conversations.length === 0) {
        conversationList.innerHTML = `
            <div class="conversation-empty">
                <i class="fas fa-comments"></i>
                <p>Asnjë bisedë akoma</p>
            </div>
        `;
        return;
    }

    conversationList.innerHTML = chatbotState.conversations.map(conv => `
        <div class="conversation-item ${conv._id === chatbotState.currentConversationId ? 'active' : ''} slide-in" 
             data-id="${conv._id}">
            <div class="conversation-avatar">
                <i class="fas fa-robot"></i>
            </div>
            <div class="conversation-content" onclick="switchToConversation('${conv._id}')">
                <div class="conversation-title">${escapeHtml(conv.title)}</div>
                <div class="conversation-preview">${escapeHtml(conv.last_message || 'Bisedë e re')}</div>
                <div class="conversation-meta">
                    <span>${conv.message_count} mesazhe</span>
                    <span>•</span>
                    <span>${formatTime(conv.last_message_time || conv.created_at)}</span>
                </div>
            </div>
            <button class="conversation-delete" onclick="event.stopPropagation(); deleteConversation('${conv._id}')" aria-label="Fshi bisedën">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `).join('');
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    
    if (diffMins < 1) return 'Tani';
    if (diffMins < 60) return `${diffMins} min më parë`;
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)} orë më parë`;
    return `${Math.floor(diffMins / 1440)} ditë më parë`;
}

window.toggleConversationList = function() {
    const sidebar = document.getElementById('conversationPanel');
    if (sidebar) {
        sidebar.classList.toggle('active');
    }
}

window.showConversationPanel = function() {
    const sidebar = document.getElementById('conversationPanel');
    if (sidebar) {
        sidebar.classList.add('active');
    }
}

window.hideConversationPanel = function() {
    const sidebar = document.getElementById('conversationPanel');
    if (sidebar) {
        sidebar.classList.remove('active');
    }
}

window.createNewConversationAndHide = async function() {
    await createNewConversation();
    hideConversationPanel();
}

window.clearChatInput = function() {
    const input = document.getElementById('chatbotInput');
    const clearBtn = document.getElementById('clearBtn');
    if (input) input.value = '';
    if (clearBtn) clearBtn.style.display = 'none';
}

window.toggleChatbot = function (forceOpen = null) {
    const { panel, input } = getChatbotElements();
    if (!panel) return;

    const shouldOpen = forceOpen === null ? !panel.classList.contains('active') : Boolean(forceOpen);

    if (shouldOpen) {
        panel.classList.add('active');
        panel.setAttribute('aria-hidden', 'false');
        chatbotState.openedOnce = true;
        
        // Load conversations on first open
        if (!panel.dataset.initialized) {
            panel.dataset.initialized = 'true';
            loadConversations();
            // Show welcome screen - no initial message anymore
        }
        setTimeout(() => input && input.focus(), 50);
    } else {
        panel.classList.remove('active');
        panel.setAttribute('aria-hidden', 'true');
    }
};

document.addEventListener('DOMContentLoaded', () => {
    const { form, input } = getChatbotElements();
    document.addEventListener('click', (event) => {
        const chip = event.target.closest('.chatbot-chip');
        if (chip && chip.tagName === 'BUTTON') {
            const message = chip.textContent.trim();
            if (message) {
                const { input: chatbotInput } = getChatbotElements();
                if (chatbotInput) {
                    chatbotInput.value = message;
                }
                sendChatbotMessage(message);
            }
            return;
        }

        const closeButton = event.target.closest('.chatbot-attachments-close');
        if (!closeButton) return;
        const attachments = closeButton.closest('.chatbot-attachments');
        if (attachments) {
            attachments.classList.add('collapsed');
        }
    });
    if (form) {
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            sendChatbotMessage();
        });
    }
    if (input) {
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                sendChatbotMessage();
            }
        });
        
        // Show/hide clear button based on input
        input.addEventListener('input', (event) => {
            const clearBtn = document.getElementById('clearBtn');
            if (clearBtn) {
                clearBtn.style.display = event.target.value ? 'flex' : 'none';
            }
        });
    }
    
    // Handle suggestion chips
    document.addEventListener('click', (event) => {
        const chip = event.target.closest('.suggestion-chip');
        if (chip) {
            const message = chip.querySelector('span')?.textContent || chip.textContent.trim();
            if (message) {
                sendChatbotMessage(message);
            }
        }
    });
});

// ===== DYNAMIC SUGGESTIONS SYSTEM =====
const SUGGESTION_TOPICS = {
    default: [
        { icon: 'fa-face-smile', text: 'Produkte për akne', keywords: ['akne', 'fytyre', 'kujdes'] },
        { icon: 'fa-pills', text: 'Vitaminë C', keywords: ['vitamin', 'imunitet', 'shëndet'] },
        { icon: 'fa-droplet', text: 'Krem hidratues', keywords: ['krem', 'hidratim', 'lëkurë'] },
        { icon: 'fa-sun', text: 'Mbrojtje dielli', keywords: ['diell', 'spf', 'mbrojtje'] },
        { icon: 'fa-heart', text: 'Produkte për zemër', keywords: ['zemër', 'qarkullim', 'shëndet'] },
        { icon: 'fa-baby', text: 'Produkte për fëmijë', keywords: ['fëmijë', 'bebe', 'nënë'] }
    ],
    akne: [
        { icon: 'fa-soap', text: 'Pastrues për akne', keywords: [] },
        { icon: 'fa-pump-soap', text: 'Tonik për fytyrë', keywords: [] },
        { icon: 'fa-sun', text: 'Krem me SPF për akne', keywords: [] },
        { icon: 'fa-moon', text: 'Krem natë për akne', keywords: [] }
    ],
    vitamina: [
        { icon: 'fa-capsules', text: 'Vitaminë D3', keywords: [] },
        { icon: 'fa-pills', text: 'Vitaminë B12', keywords: [] },
        { icon: 'fa-tablets', text: 'Multivitamina', keywords: [] },
        { icon: 'fa-candy-cane', text: 'Vitaminë C + Zinc', keywords: [] }
    ],
    dielli: [
        { icon: 'fa-pump-soap', text: 'Sunscreen SPF 50', keywords: [] },
        { icon: 'fa-baby', text: 'Sunscreen për fëmijë', keywords: [] },
        { icon: 'fa-face-smile', text: 'Sunscreen për fytyrë', keywords: [] },
        { icon: 'fa-water', text: 'Sunscreen waterproof', keywords: [] }
    ],
    floket: [
        { icon: 'fa-pump-soap', text: 'Shampo kundër zbokthit', keywords: [] },
        { icon: 'fa-droplet', text: 'Maskë për flokë', keywords: [] },
        { icon: 'fa-spray', text: 'Serum për flokë', keywords: [] },
        { icon: 'fa-wind', text: 'Conditioner hidratues', keywords: [] }
    ]
};

let currentSuggestionTopic = 'default';

window.updateDynamicSuggestions = function(message, isUser = true) {
    const container = document.getElementById('suggestionsContainer');
    const list = document.getElementById('suggestionsList');
    if (!container || !list) return;
    
    // Determine topic based on message content
    const msg = message.toLowerCase();
    let newTopic = 'default';
    
    if (msg.includes('akne') || msg.includes('puçrra') || msg.includes('fytyr')) newTopic = 'akne';
    else if (msg.includes('vitamin') || msg.includes('suplement')) newTopic = 'vitamina';
    else if (msg.includes('diell') || msg.includes('spf') || msg.includes('sun')) newTopic = 'dielli';
    else if (msg.includes('flok') || msg.includes('shampo') || msg.includes('kondicioner')) newTopic = 'floket';
    
    currentSuggestionTopic = newTopic;
    const suggestions = SUGGESTION_TOPICS[newTopic] || SUGGESTION_TOPICS.default;
    
    // Shuffle and pick 4 random suggestions
    const shuffled = [...suggestions].sort(() => 0.5 - Math.random()).slice(0, 4);
    
    // Render suggestions
    list.innerHTML = shuffled.map(s => `
        <button class="suggestion-pill" onclick="sendChatbotMessage('${escapeHtml(s.text)}')">
            <i class="fas ${s.icon}"></i>
            <span>${escapeHtml(s.text)}</span>
        </button>
    `).join('');
    
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
};

window.refreshSuggestions = function() {
    const refreshBtn = document.querySelector('.suggestions-refresh');
    if (refreshBtn) refreshBtn.classList.add('spinning');
    
    // Get last message for context
    const messages = document.querySelectorAll('.chatbot-message');
    let lastMsg = '';
    if (messages.length > 0) {
        const lastBubble = messages[messages.length - 1].querySelector('.message-bubble');
        if (lastBubble) lastMsg = lastBubble.textContent;
    }
    
    updateDynamicSuggestions(lastMsg || 'default', false);
    
    setTimeout(() => {
        if (refreshBtn) refreshBtn.classList.remove('spinning');
    }, 500);
};

window.hideSuggestions = function() {
    const container = document.getElementById('suggestionsContainer');
    if (container) container.style.display = 'none';
};

// ===== CONVERSATION FILTERING =====
window.filterConversations = function(searchTerm) {
    const items = document.querySelectorAll('.conversation-item');
    const term = searchTerm.toLowerCase().trim();
    
    items.forEach(item => {
        const title = item.querySelector('.conversation-title')?.textContent.toLowerCase() || '';
        const preview = item.querySelector('.conversation-preview')?.textContent.toLowerCase() || '';
        
        if (term === '' || title.includes(term) || preview.includes(term)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
};

// Update conversation count in sidebar
function updateConversationCount() {
    const countEl = document.getElementById('conversationCount');
    if (countEl) {
        const count = chatbotState.conversations?.length || 0;
        countEl.textContent = `${count} bised${count === 1 ? 'ë' : 'a'}`;
    }
}

// Override updateConversationUI to include count update
const originalUpdateConversationUI = updateConversationUI;
updateConversationUI = function() {
    originalUpdateConversationUI();
    updateConversationCount();
};

// Override sendChatbotMessage to show suggestions after response
const originalSendChatbotMessage = sendChatbotMessage;
sendChatbotMessage = async function(messageOverride = null) {
    const input = document.getElementById('chatbotInput');
    const message = String(messageOverride !== null ? messageOverride : input?.value).trim();
    
    // Update suggestions based on user message
    if (message) {
        updateDynamicSuggestions(message, true);
    }
    
    await originalSendChatbotMessage(messageOverride);
    
    // Update suggestions based on AI response (after a short delay)
    setTimeout(() => {
        const messages = document.querySelectorAll('.chatbot-message.bot');
        if (messages.length > 0) {
            const lastMsg = messages[messages.length - 1].querySelector('.message-bubble')?.textContent || '';
            updateDynamicSuggestions(lastMsg, false);
        }
    }, 100);
};
