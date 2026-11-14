import sys
import os
import pandas as pd

def main():
    # Comprobación defensiva de argumentos de entrada
    if len(sys.argv) < 2:
        sys.stderr.write("Error: Falta la ruta del archivo CSV como argumento.\n")
        sys.exit(1)
    
    file_path = sys.argv[1]
    
    # Validación de existencia y formato del fichero
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        sys.stderr.write(f"Error crítico: El fichero '{file_path}' no existe o no es un archivo válido.\n")
        sys.exit(1)
        
    try:
        # Lectura y parseo defensivo con pandas
        df = pd.read_csv(file_path)
        if df.empty:
            sys.stderr.write(f"Error: El fichero CSV '{file_path}' está vacío.\n")
            sys.exit(1)
    except pd.errors.EmptyDataError:
        sys.stderr.write(f"Error de parseo: El fichero '{file_path}' está vacío o corrupto.\n")
        sys.exit(1)
    except pd.errors.ParserError:
        sys.stderr.write(f"Error de parseo: No se pudo interpretar el formato CSV en '{file_path}'.\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error inesperado al leer el archivo de datos: {str(e)}\n")
        sys.exit(1)
        
    try:
        # Operación de exportación protegida
        output_path = "data/results.csv"
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"Análisis completado y exportado con éxito a {output_path}")
    except (OSError, IOError) as e:
        sys.stderr.write(f"Error de I/O al exportar los resultados del análisis: {str(e)}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"Error inesperado durante la exportación: {str(e)}\n")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"Error fatal no controlado en el script de análisis: {str(e)}\n")
        sys.exit(1)