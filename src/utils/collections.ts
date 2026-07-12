/**
 * Filtra una colección de objetos basándose en criterios de igualdad dinámicos.
 * Soporta múltiples filtros simultáneos (operación lógica AND).
 * * @param array Colección de elementos a filtrar.
 * @param criteria Objeto con las propiedades y valores que deben cumplirse.
 * @returns Nuevo array con los elementos que cumplen todos los criterios.
 */
export const filterCollection = <T>(array: T[], criteria: Partial<T>): T[] => {
    if (!array || array.length === 0) return [];

    return array.filter(item => {
        for (const key in criteria) {
            if (criteria[key] !== undefined && item[key] !== criteria[key]) {
                return false; // Al primer criterio que no coincida, lo descartamos
            }
        }
        return true;
    });
};

/**
 * Ordena una colección de objetos por una propiedad específica de forma ascendente o descendente.
 * Es una función pura; no muta el array original.
 * * @param array Colección de elementos a ordenar.
 * @param key Propiedad del objeto por la cual ordenar.
 * @param order Dirección de la ordenación: 'asc' o 'desc'. Por defecto 'asc'.
 * @returns Nuevo array ordenado.
 */
export const sortCollection = <T>(array: T[], key: keyof T, order: 'asc' | 'desc' = 'asc'): T[] => {
    if (!array || array.length === 0) return [];

    // Clonamos el array para mantener la función pura
    const clonedArray = [...array];

    return clonedArray.sort((a, b) => {
        const valueA = a[key];
        const valueB = b[key];

        if (valueA === valueB) return 0;

        if (order === 'asc') {
            return valueA > valueB ? 1 : -1;
        } else {
            return valueA < valueB ? 1 : -1;
        }
    });
};

/**
 * Agrupa una colección de objetos según el valor de una de sus propiedades.
 * Muy útil para organizar datos de cara a los analistas y operarios de TrackFlow.
 * * @param array Colección de elementos.
 * @param key Propiedad del objeto que se usará como clave de agrupación.
 * @returns Un objeto indexado donde las llaves son los valores de la propiedad y los valores son arrays de elementos.
 */
export const groupCollectionBy = <T>(array: T[], key: keyof T): Record<string, T[]> => {
    if (!array || array.length === 0) return {};

    return array.reduce((accumulator, item) => {
        // Forzamos la conversión a string de la propiedad para usarla como clave del Record
        const groupKey = String(item[key]);

        if (!accumulator[groupKey]) {
            accumulator[groupKey] = [];
        }

        accumulator[groupKey].push(item);
        return accumulator;
    }, {} as Record<string, T[]>);
};