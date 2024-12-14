"""
Budgie main
"""
import pyfiglet
from budgie.singletons import console, logger

header = pyfiglet.figlet_format("Budgie", font="slant")

def main():
    console.print(header, style="bold blue")
    logger.info("Budgie started!")
    console.print("Budgie!")

if __name__ == "__main__":
    main()
