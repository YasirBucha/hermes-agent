import type { useSensors } from '@dnd-kit/core'
import { closestCenter, DndContext, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import { arrayMove, SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import type * as React from 'react'
import { useState } from 'react'

import { cn } from '@/lib/utils'

// Sidebar reordering is a strictly vertical list. The dragged item's transform
// is rendered Y-only in useSortableBindings (with a subtle 1.018 lift scale);
// this stops dnd-kit's auto-scroll from dragging the rail — or the window —
// sideways when the pointer nears an edge, killing the horizontal "drag to valhalla".
const reorderAutoScroll = { threshold: { x: 0, y: 0.2 } }

const BOUNDED_REORDER_TRANSITION = {
  duration: 180,
  easing: 'cubic-bezier(0.22, 1, 0.36, 1)'
}

// One self-contained, nesting-safe reorderable list. It owns its DndContext, so a
// drag only ever collides with THIS list's own items — drop it at any depth (repos,
// worktrees, sessions) and reordering "just works" without leaking into the lists
// around or inside it. Pair each item with useSortableBindings(id); the list reports
// the new id order and the caller persists it. This is the single generic primitive
// behind every reorderable surface in the sidebar.
export function ReorderableList({
  children,
  ids,
  onReorder,
  sensors
}: {
  children: React.ReactNode
  ids: string[]
  onReorder: (ids: string[]) => void
  sensors?: ReturnType<typeof useSensors>
}) {
  const [activeId, setActiveId] = useState<null | string>(null)

  const handleDragStart = ({ active }: DragStartEvent) => {
    setActiveId(String(active.id))
  }

  const handleDragCancel = () => {
    setActiveId(null)
  }

  const handleDragEnd = ({ activatorEvent, active, over }: DragEndEvent) => {
    setActiveId(null)

    // dnd-kit only restores focus for keyboard drags; after a pointer drop the
    // browser leaves :focus on the grab handle, which keeps a focus-within
    // grabber/affordance reveal stuck "on". Drop that focus so the row returns
    // to its resting state once the pointer moves away.
    if (!(activatorEvent instanceof KeyboardEvent)) {
      ;(document.activeElement as HTMLElement | null)?.blur()
    }

    if (!over || active.id === over.id) {
      return
    }

    const from = ids.indexOf(String(active.id))
    const to = ids.indexOf(String(over.id))

    if (from >= 0 && to >= 0) {
      onReorder(arrayMove(ids, from, to))
    }
  }

  return (
    <DndContext
      autoScroll={reorderAutoScroll}
      collisionDetection={closestCenter}
      onDragCancel={handleDragCancel}
      onDragEnd={handleDragEnd}
      onDragStart={handleDragStart}
      sensors={sensors}
    >
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <div
          className={cn(
            'rounded-[10px] border-[1.5px] border-solid transition-[border-color,background-color,box-shadow] duration-[180ms] ease-[cubic-bezier(0.22,1,0.36,1)]',
            activeId !== null
              ? 'border-primary bg-primary/[0.06] dark:bg-primary/[0.09] shadow-[0_6px_12px_0.5px_rgba(99,102,241,0.18)]'
              : 'border-transparent'
          )}
          data-bounded-reorder-active={activeId !== null ? 'true' : 'false'}
          data-bounded-reorder-container="sidebar-reorderable-list"
        >
          {children}
        </div>
      </SortableContext>
    </DndContext>
  )
}

export function useSortableBindings(id: string) {
  const { attributes, isDragging, listeners, setNodeRef, transform, transition } = useSortable({
    id,
    transition: BOUNDED_REORDER_TRANSITION
  })

  const translateY = transform ? `translate3d(0px, ${transform.y}px, 0)` : undefined

  return {
    dragging: isDragging,
    dragHandleProps: { ...attributes, ...listeners },
    ref: setNodeRef,
    reorderable: true as const,
    style: {
      // Uniform vertical list: translate on Y and apply a subtle 1.018 lift scale when dragging.
      transform: isDragging
        ? `${translateY ?? 'translate3d(0px, 0px, 0)'} scale(1.018)`
        : translateY,
      transition: isDragging ? undefined : transition,
      willChange: isDragging ? 'transform' : undefined
    }
  }
}
