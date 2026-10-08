/**
 * Issued web reader – trash page: restore a trashed comic, or forget a deleted one
 */
(() => {
  const toast = (icon, title, text, timer = 3000) =>
    Swal.fire({ icon, title, text, toast: true, position: 'top-end', showConfirmButton: false, timer, timerProgressBar: true });

  const errorDetail = async (res) => {
    try {
      const payload = await res.json();
      if (typeof payload?.detail === 'string') return payload.detail;
    } catch { /* ignore JSON parse errors */ }
    return 'Please try again.';
  };

  document.addEventListener('click', async (evt) => {
    const btn = evt.target.closest('.trash-action');
    if (!btn || btn.disabled) return;
    const row = btn.closest('.trash-row');
    const traceId = row?.dataset.traceId;
    if (!traceId) return;

    const restoring = btn.dataset.action === 'restore';
    if (!restoring) {
      const answer = await Swal.fire({
        icon: 'question',
        title: 'Forget this comic?',
        text: `A file named "${btn.dataset.filename}" will be imported again by the next scan.`,
        showCancelButton: true,
        confirmButtonText: 'Forget',
      });
      if (!answer.isConfirmed) return;
    }

    btn.disabled = true;
    try {
      const res = await fetch(
        restoring ? `/reader/api/trash/${traceId}/restore` : `/reader/api/trash/${traceId}`,
        { method: restoring ? 'POST' : 'DELETE' },
      );
      if (!res.ok) {
        toast('error', restoring ? 'Restore failed' : 'Forget failed', await errorDetail(res), 4500);
        btn.disabled = false;
        return;
      }
      row.remove();
      toast('success', restoring ? 'Restored' : 'Forgotten', btn.dataset.filename, 2000);
      // Show the "No deleted comics" message once the list is empty.
      if (!document.querySelector('.trash-row')) setTimeout(() => window.location.reload(), 800);
    } catch {
      toast('error', 'Network error', 'Please try again.');
      btn.disabled = false;
    }
  });
})();
