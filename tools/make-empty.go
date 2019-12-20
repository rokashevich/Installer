package main

import "os"

func main() {
	if len(os.Args) == 2 {
		if _, err := os.Stat(os.Args[1]); err == nil { // Каталог существует.
			if os.RemoveAll(os.Args[1]) != nil { // Каталог не удалось удалить.
				os.Exit(2)
			}
		}
		if os.MkdirAll(os.Args[1], 0777) == nil { // Каталог удалось создать.
			os.Exit(0)
		}
	}
	os.Exit(1)
}
