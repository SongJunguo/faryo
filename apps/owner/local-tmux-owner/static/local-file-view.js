(() => {
  'use strict';

  const back = document.getElementById('backButton');
  back?.addEventListener('click', () => {
    if (history.length > 1) history.back();
    else location.assign('../../');
  });
})();
