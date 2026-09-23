(function () {
    'use strict';

    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"]/g, function (char) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char];
        });
    }

    function openInvoice(data) {
        var invoiceWindow = window.open('', '_blank', 'width=900,height=980');
        if (!invoiceWindow) {
            window.alert('Lejoni dritaret pop-up për të hapur faturën.');
            return;
        }

        var details = (data.details || []).filter(function (row) { return row && row.value; });
        var items = data.items || [];
        var totals = data.totals || [];
        var html = `<!doctype html><html lang="sq"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Faturë #${escapeHtml(data.orderId)}</title>
        <style>
          :root{--ink:#172033;--muted:#66758d;--soft:#eef2f5;--brand:#4f5d4e;--paper:#fff}
          *{box-sizing:border-box}body{margin:0;background:#eef1ef;color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
          .invoice{width:min(850px,calc(100% - 32px));margin:32px auto 20px;background:var(--paper);padding:48px 52px;border-radius:18px;box-shadow:0 14px 44px rgba(29,43,34,.10)}
          .header{display:flex;justify-content:space-between;align-items:flex-start;gap:30px;padding-bottom:24px;border-bottom:3px solid var(--brand)}
          .brand{font-size:25px;line-height:1.15;font-weight:800;color:var(--brand);letter-spacing:-.02em}.contact{margin-top:8px;color:var(--muted);font-size:13px}.contact div+div{margin-top:2px}
          .invoice-meta{text-align:right}.invoice-title{font-size:27px;font-weight:850;letter-spacing:.04em}.invoice-number{display:inline-block;margin-top:8px;padding:4px 9px;border-radius:6px;background:#f0f3f0;color:var(--brand);font-weight:800}.invoice-date{margin-top:7px;color:var(--muted)}
          .section{margin-top:28px}.section-title{margin:0 0 12px;color:var(--muted);font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}
          .customer-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 34px}.detail{padding:9px 0;border-bottom:1px solid var(--soft);min-width:0}.detail-label{display:block;color:#8c99ad;font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;margin-bottom:2px}.detail-value{font-weight:600;overflow-wrap:anywhere}
          table{width:100%;border-collapse:collapse;font-size:13px}thead{background:var(--brand);color:#fff}th{padding:11px 13px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em}th:first-child{width:76px}th:last-child,td:last-child{text-align:right}td{padding:12px 13px;border-bottom:1px solid var(--soft)}
          .totals{width:min(350px,100%);margin:17px 0 0 auto}.total-row{display:flex;justify-content:space-between;gap:20px;padding:6px 0;color:var(--muted)}.total-row.grand{margin-top:5px;padding-top:11px;border-top:2px solid var(--brand);font-size:17px;font-weight:850;color:var(--ink)}
          .footer{margin-top:42px;padding-top:17px;border-top:1px solid var(--soft);display:flex;justify-content:space-between;gap:20px;color:#8c99ad;font-size:11px}.footer strong{color:var(--brand)}
          .actions{display:flex;justify-content:center;gap:10px;margin:0 auto 32px}.actions button{border:1px solid #d6ddd7;border-radius:10px;padding:10px 17px;background:#fff;color:var(--brand);font:inherit;font-weight:750;cursor:pointer}.actions .primary{border-color:var(--brand);background:var(--brand);color:#fff}
          @media(max-width:620px){.invoice{width:100%;margin:0;padding:28px 22px;border-radius:0;box-shadow:none}.header{flex-direction:column;gap:18px}.invoice-meta{text-align:left}.customer-grid{grid-template-columns:1fr}.footer{flex-direction:column}.actions{margin-top:18px}.brand{font-size:22px}}
          @media print{@page{size:A4;margin:16mm}body{background:#fff}.invoice{width:100%;margin:0;padding:0;border-radius:0;box-shadow:none}.actions{display:none}}
        </style></head><body>
        <main class="invoice"><header class="header"><div><div class="brand">Barnatore Meld Pharm</div><div class="contact"><div>72 Eqrem Çabej, Prishtinë 10000</div><div>+383 45 590 455 · info@meldpharm.com</div></div></div><div class="invoice-meta"><div class="invoice-title">FATURË</div><div class="invoice-number">#${escapeHtml(data.orderId)}</div><div class="invoice-date">${escapeHtml(data.date)}</div></div></header>
        <section class="section"><h2 class="section-title">Informacioni i klientit</h2><div class="customer-grid">${details.map(function (row) { return `<div class="detail"><span class="detail-label">${escapeHtml(row.label)}</span><span class="detail-value">${escapeHtml(row.value)}</span></div>`; }).join('')}</div></section>
        <section class="section"><h2 class="section-title">Produktet</h2><table><thead><tr><th>Sasia</th><th>Produkti</th><th>Çmimi</th></tr></thead><tbody>${items.map(function (item) { return `<tr><td>${escapeHtml(item.quantity)}×</td><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.price)}</td></tr>`; }).join('')}</tbody></table><div class="totals">${totals.map(function (row) { return `<div class="total-row${row.grand ? ' grand' : ''}"><span>${escapeHtml(row.label)}</span><span>${escapeHtml(row.value)}</span></div>`; }).join('')}</div></section>
        <footer class="footer"><span>Faleminderit për besimin tuaj!</span><strong>barnatoremeldpharm.com</strong></footer></main>
        <div class="actions"><button type="button" onclick="window.close()">Mbyll</button><button type="button" class="primary" onclick="window.print()">Printo / Ruaj PDF</button></div></body></html>`;

        invoiceWindow.document.open();
        invoiceWindow.document.write(html);
        invoiceWindow.document.close();
    }

    window.MeldInvoice = { open: openInvoice };
}());
