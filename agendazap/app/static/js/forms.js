/* Padronizacao de campos de formulario do AgendaZap.
   Aplica mascara de telefone (00) 00000-0000 em qualquer input[type="tel"].
   O backend (clean_phone) remove tudo que nao for digito, entao a mascara e
   apenas visual e nunca quebra o envio. */
(function () {
  function maskPhone(value) {
    var d = (value || '').replace(/\D/g, '').slice(0, 11);
    if (!d) return '';
    if (d.length <= 2) return '(' + d;
    if (d.length <= 6) return '(' + d.slice(0, 2) + ') ' + d.slice(2);
    if (d.length <= 10) return '(' + d.slice(0, 2) + ') ' + d.slice(2, 6) + '-' + d.slice(6);
    return '(' + d.slice(0, 2) + ') ' + d.slice(2, 7) + '-' + d.slice(7);
  }

  function attach(el) {
    if (el.value) el.value = maskPhone(el.value); // formata valor pre-preenchido
    el.addEventListener('input', function () {
      el.value = maskPhone(el.value);
    });
  }

  function init() {
    document.querySelectorAll('input[type="tel"]').forEach(attach);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
