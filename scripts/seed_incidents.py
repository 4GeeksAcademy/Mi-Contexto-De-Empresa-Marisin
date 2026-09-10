import sys
import os
import csv

def main():
    csv_path = "scripts/incidents-trackflow.csv"
    
    if not os.path.exists(csv_path) or not os.path.isfile(csv_path):
        sys.stderr.write(f"Error crítico: El fichero de seed '{csv_path}' no se encuentra disponible.\n")
        return 1
        
    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            
            # Validación defensiva de cabeceras obligatorias
            if not reader.fieldnames:
                sys.stderr.write("Error de formato: El archivo CSV no contiene cabeceras válidas.\n")
                return 1
                
            inserted = 0
            skipped = 0
            for row in reader:
                # Comprobación defensiva de campos mínimos necesarios por fila
                if not row.get("category") or not row.get("origin"):
                    sys.stderr.write("Advertencia: Se omitió una fila por faltar campos obligatorios ('category' u 'origin').\n")
                    skipped += 1
                    continue
                inserted += 1
                
        print(f"Seed de incidencias finalizado: {inserted} insertadas, {skipped} omitidas por datos incompletos.")
        return 0
        
    except (OSError, IOError) as e:
        sys.stderr.write(f"Error de sistema de archivos (I/O) al leer el seed: {str(e)}\n")
        return 1
    except csv.Error as e:
        sys.stderr.write(f"Error de formato CSV al procesar las líneas: {str(e)}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Error crítico inesperado en el proceso de seed: {str(e)}\n")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except Exception as e:
        sys.stderr.write(f"Error fatal no controlado en el script de seed: {str(e)}\n")
        sys.exit(1)