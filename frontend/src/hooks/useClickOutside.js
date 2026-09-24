import { useEffect, useRef } from "react";

export function useClickOutside(ref, handler) {
  const handlerRef = useRef(handler);
  
  // Обновляем реф на актуальный хендлер при каждом рендере, 
  // чтобы не терять замыкания, если они есть.
  useEffect(() => {
    handlerRef.current = handler;
  }, [handler]);

  useEffect(() => {
    const listener = (event) => {
      // Если клик был внутри элемента, на который указывает ref — игнорируем
      if (!ref.current || ref.current.contains(event.target)) {
        return;
      }
      handlerRef.current(event);
    };

    document.addEventListener("mousedown", listener);
    document.addEventListener("touchstart", listener);

    return () => {
      document.removeEventListener("mousedown", listener);
      document.removeEventListener("touchstart", listener);
    };
  }, [ref]);
}
