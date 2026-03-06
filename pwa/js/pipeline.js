/**
 * Pipeline Kanban — drag-and-drop mobile + desktop
 */

var _kanbanColumns = [
  { key: "dm_sent", emoji: "\uD83D\uDCAC", label: "New" },
  { key: "replied", emoji: "\uD83D\uDC41\uFE0F", label: "Suivi" },
  { key: "interested", emoji: "\uD83D\uDD25", label: "Intéressé" },
  { key: "rdv", emoji: "\uD83D\uDCC5", label: "RDV" },
  { key: "converted", emoji: "\u2705", label: "Converti" },
  { key: "lost", emoji: "\u274C", label: "Perdu" },
];

var _dragData = null;

async function renderPipeline(container) {
  render(container, [
    '<div class="page-header"><h1>\uD83C\uDFAF Pipeline</h1></div>',
    '<div class="kanban-board" id="kanban-board">',
    _kanbanColumns.map(function (col) {
      return [
        '<div class="kanban-column" data-status="' + col.key + '">',
        '  <div class="kanban-column-header">',
        "    <span>" + col.emoji + " " + esc(col.label) + "</span>",
        '    <span class="kanban-count" id="count-' + col.key + '">0</span>',
        "  </div>",
        '  <div class="kanban-cards" id="col-' + col.key + '"></div>',
        "</div>",
      ].join("\n");
    }).join("\n"),
    "</div>",
  ].join("\n"));

  // Load data for each column
  await _loadKanban();
}

async function _loadKanban() {
  var promises = _kanbanColumns.map(function (col) {
    return API.getProspects({ status: col.key, per_page: 50 })
      .then(function (data) { return { key: col.key, items: data.items || data || [] }; })
      .catch(function () { return { key: col.key, items: [] }; });
  });

  var results = await Promise.all(promises);

  results.forEach(function (res) {
    var colEl = document.getElementById("col-" + res.key);
    var countEl = document.getElementById("count-" + res.key);
    if (!colEl) return;

    colEl.textContent = "";
    if (countEl) countEl.textContent = res.items.length;

    res.items.forEach(function (prospect) {
      var card = _createCard(prospect);
      colEl.appendChild(card);
    });
  });
}

function _createCard(prospect) {
  var card = document.createElement("div");
  card.className = "kanban-card";
  card.dataset.prospectId = prospect.id;
  card.draggable = true;

  render(card, [
    '<div class="kanban-card-header">',
    '  <span class="kanban-card-name">@' + esc(prospect.username || "?") + "</span>",
    "  " + scoreBadge(prospect.score),
    "</div>",
    '<div class="kanban-card-info">',
    '  <span class="text-secondary">' + esc(prospect.full_name || "") + "</span>",
    prospect.city ? '  <span class="text-secondary">\uD83D\uDCCD ' + esc(prospect.city) + "</span>" : "",
    "</div>",
  ].join("\n"));

  // Tap to open conversation
  card.addEventListener("click", function (e) {
    if (_dragData) return; // Don't navigate during drag
    navigateTo("#/conversation/" + prospect.id);
  });

  // Desktop drag
  card.addEventListener("dragstart", function (e) {
    _dragData = { prospectId: prospect.id, fromStatus: prospect.status };
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });

  card.addEventListener("dragend", function () {
    card.classList.remove("dragging");
    _dragData = null;
  });

  // Mobile touch drag
  var touchStartY = 0;
  var touchStartX = 0;
  var isDragging = false;

  card.addEventListener("touchstart", function (e) {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    isDragging = false;
  }, { passive: true });

  card.addEventListener("touchmove", function (e) {
    var dx = Math.abs(e.touches[0].clientX - touchStartX);
    var dy = Math.abs(e.touches[0].clientY - touchStartY);
    if (dx > 10 || dy > 10) isDragging = true;

    if (isDragging) {
      card.classList.add("dragging");
      _dragData = { prospectId: prospect.id, fromStatus: prospect.status };
    }
  }, { passive: true });

  card.addEventListener("touchend", function (e) {
    if (isDragging && _dragData) {
      var touch = e.changedTouches[0];
      var dropTarget = document.elementFromPoint(touch.clientX, touch.clientY);
      var column = dropTarget ? dropTarget.closest(".kanban-column") : null;

      if (column) {
        var newStatus = column.dataset.status;
        if (newStatus && newStatus !== _dragData.fromStatus) {
          _moveProspect(_dragData.prospectId, newStatus, card, column);
        }
      }
    }
    card.classList.remove("dragging");
    _dragData = null;
    isDragging = false;
  });

  return card;
}

// Desktop drop zones
document.addEventListener("DOMContentLoaded", function () {
  document.addEventListener("dragover", function (e) {
    var column = e.target.closest(".kanban-column");
    if (column && _dragData) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      column.classList.add("drag-over");
    }
  });

  document.addEventListener("dragleave", function (e) {
    var column = e.target.closest(".kanban-column");
    if (column) column.classList.remove("drag-over");
  });

  document.addEventListener("drop", function (e) {
    e.preventDefault();
    var column = e.target.closest(".kanban-column");
    if (column) column.classList.remove("drag-over");

    if (column && _dragData) {
      var newStatus = column.dataset.status;
      if (newStatus && newStatus !== _dragData.fromStatus) {
        var card = document.querySelector('[data-prospect-id="' + _dragData.prospectId + '"]');
        if (card) _moveProspect(_dragData.prospectId, newStatus, card, column);
      }
    }
    _dragData = null;
  });
});

async function _moveProspect(prospectId, newStatus, card, column) {
  // Optimistic UI: move card
  var cardsContainer = column.querySelector(".kanban-cards");
  if (cardsContainer && card) {
    // Update counts
    var oldCol = card.parentElement;
    cardsContainer.appendChild(card);

    _updateColCount(oldCol);
    _updateColCount(cardsContainer);
  }

  try {
    await API.updateProspect(prospectId, { status: newStatus });
    showToast("Prospect déplacé vers " + newStatus, "success");
  } catch (e) {
    showToast("Erreur déplacement", "error");
    _loadKanban(); // Revert
  }
}

function _updateColCount(colCards) {
  if (!colCards) return;
  var column = colCards.closest(".kanban-column");
  if (!column) return;
  var status = column.dataset.status;
  var countEl = document.getElementById("count-" + status);
  if (countEl) countEl.textContent = colCards.children.length;
}
