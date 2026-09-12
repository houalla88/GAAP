/* Calcul de dimensionnement en direct sur le formulaire de conception.
 *
 * Amelioration progressive stricte : sans JavaScript, le formulaire reste
 * entierement utilisable et les memes controles sont appliques cote serveur a
 * l'enregistrement. Ce script n'ajoute qu'une chose - voir tout de suite si le
 * plan est capable de conclure, plutot que trois semaines apres le lancement.
 *
 * Aucun calcul statistique n'est fait ici : tout passe par /api/v1/design/power,
 * de sorte qu'il n'existe qu'une seule implementation de la formule de
 * dimensionnement dans le systeme.
 */
(function () {
  "use strict";

  var readout = document.getElementById("power-readout");
  if (!readout) { return; }

  var endpoint = readout.getAttribute("data-endpoint");
  var form = readout.closest("form");
  if (!form || !endpoint) { return; }

  function number(name, fallback) {
    var field = form.querySelector("[name='" + name + "']");
    if (!field) { return fallback; }
    var parsed = parseFloat(String(field.value).replace(",", "."));
    return isNaN(parsed) ? fallback : parsed;
  }

  function countCells() {
    var filled = 0;
    form.querySelectorAll("[name='cell_rate']").forEach(function (field) {
      if (String(field.value).trim() !== "") { filled += 1; }
    });
    return Math.max(2, filled);
  }

  function set(field, value) {
    var node = readout.querySelector("[data-field='" + field + "']");
    if (node) { node.textContent = value; }
  }

  function french(value, digits) {
    return value.toFixed(digits === undefined ? 0 : digits).replace(".", ",");
  }

  var pending = null;

  function refresh() {
    var payload = {
      baseline_rate: number("baseline_rate", 6) / 100,
      target_mde: number("target_mde", 15) / 100,
      alpha: number("alpha", 5) / 100,
      power: number("power", 80) / 100,
      cells: countCells(),
      planned_volume: number("planned_volume", 0)
    };

    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (response) { return response.ok ? response.json() : null; })
      .then(function (data) {
        if (!data) { return; }
        set("comparisons", String(data.comparisons));
        set("alpha_adjusted", french(data.alpha_adjusted, 4));
        set("required_per_cell", data.required_per_cell.toLocaleString("fr-BE"));
        set("available_per_cell", data.available_per_cell.toLocaleString("fr-BE"));
        set("detectable_effect",
          data.detectable_effect === null ? "—" : french(data.detectable_effect * 100, 1) + " %");
        if (data.sufficient === null) {
          set("verdict", "volume non renseigne");
        } else if (data.sufficient) {
          set("verdict", "plan dimensionne");
        } else if (data.available_per_cell < data.required_per_cell / 2) {
          set("verdict", "bloquant : sous-dimensionne");
        } else {
          set("verdict", "avertissement : puissance faible");
        }
      })
      .catch(function () { /* Le formulaire reste utilisable sans cette aide. */ });
  }

  function schedule() {
    window.clearTimeout(pending);
    pending = window.setTimeout(refresh, 250);
  }

  form.addEventListener("input", schedule);
  refresh();
})();
