/**
 * Búsqueda Lineal (Linear Search)
 * Ideal para arrays desordenados. Recorre el array elemento a elemento.
 * Complejidad temporal: O(n)
 * * @param array Colección de elementos donde buscar.
 * @param target Valor buscado.
 * @param key La propiedad del objeto por la cual queremos comparar.
 * @returns El índice del elemento si se encuentra, o -1 si no se encuentra o el array está vacío.
 */
export const linearSearch = <T>(array: T[], target: any, key: keyof T): number => {
    if (!array || array.length === 0) return -1; // Manejo explícito de casos vacíos

    for (let i = 0; i < array.length; i++) {
        if (array[i][key] === target) {
            return i; // Elemento encontrado, devolvemos el índice
        }
    }

    return -1; // Elemento no encontrado
};

/**
 * Búsqueda Binaria (Binary Search)
 * ¡ATENCIÓN!: El array DEBE estar previamente ordenado por la misma clave ('key') que se busca.
 * Divide el espacio de búsqueda a la mitad en cada paso.
 * Complejidad temporal: O(log n)
 * * @param array Colección de elementos ORDENADOS.
 * @param target Valor buscado.
 * @param key La propiedad del objeto por la cual queremos comparar.
 * @returns El índice del elemento si se encuentra, o -1 si no se encuentra o el array está vacío.
 */
export const binarySearch = <T>(array: T[], target: any, key: keyof T): number => {
    if (!array || array.length === 0) return -1; // Manejo explícito de casos vacíos

    let left = 0;
    let right = array.length - 1;

    while (left <= right) {
        const mid = Math.floor((left + right) / 2);
        const midValue = array[mid][key];

        if (midValue === target) {
            return mid; // Elemento encontrado
        }

        if (midValue < target) {
            left = mid + 1; // Descartamos la mitad izquierda
        } else {
            right = mid - 1; // Descartamos la mitad derecha
        }
    }

    return -1; // Elemento no encontrado
};