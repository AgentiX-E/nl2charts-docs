import { DndContext, useDraggable, useDroppable } from '@dnd-kit/core';
import React from 'react';
export function Demo() {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: 'tbl' });
  const { setNodeRef: dropRef } = useDroppable({ id: 'ds' });
  return React.createElement(DndContext, null,
    React.createElement('div', { ref: setNodeRef, ...listeners, ...attributes }, 'orders'),
    React.createElement('div', { ref: dropRef }, 'datasets'));
}
