/* Header dropdowns on touch and narrow screens: first tap opens the menu, second tap follows the link. */
(function () {
  var mq = window.matchMedia("(max-width:720px), (hover:none)");
  document.querySelectorAll(".nav-item").forEach(function (item) {
    var link = item.querySelector(".nav-link");
    var drop = item.querySelector(".nav-drop");
    if (!link || !drop) return;
    link.addEventListener("click", function (e) {
      if (!mq.matches || item.classList.contains("open")) return;
      e.preventDefault();
      document.querySelectorAll(".nav-item.open").forEach(function (o) { o.classList.remove("open"); });
      item.classList.add("open");
      if (window.matchMedia("(max-width:720px)").matches) drop.style.top = (link.getBoundingClientRect().bottom + 6) + "px";
    });
  });
  document.addEventListener("click", function (e) {
    if (!e.target.closest(".nav-item")) {
      document.querySelectorAll(".nav-item.open").forEach(function (o) { o.classList.remove("open"); });
    }
  });
})();
