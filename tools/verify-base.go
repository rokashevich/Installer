package main

import (
	"bufio"
	"crypto/md5"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"strings"
)

func hash_file_md5(filePath string) string {
	file, err := os.Open(filePath)
	if err != nil {
		return ""
	}

	//Tell the program to call the following function when the current function returns
	defer file.Close()

	//Open a new hash interface to write to
	hash := md5.New()

	//Copy the file in the hash interface and check for any error
	if _, err := io.Copy(hash, file); err != nil {
		return ""
	}

	//Get the 16 bytes hash
	hashInBytes := hash.Sum(nil)[:16]

	//Convert the bytes to a string
	return hex.EncodeToString(hashInBytes)

}

func main() {
	if _, err := os.Stat("base.txt"); os.IsNotExist(err) {
		fmt.Println("base.txt not found")
		os.Exit(1)
	}

	file, err := os.Open("base.txt")
	defer file.Close()

	if err != nil {
		fmt.Println("error opening base.txt")
		os.Exit(1)
	}

	reader := bufio.NewReader(file)

	var error_message = ""

	var line string
	for {
		line, err = reader.ReadString('\n')
		if strings.HasPrefix(line, "md5 ") {
			words := strings.SplitN(line, " ", 3)
			words[2] = strings.TrimSpace(words[2])
			hash := hash_file_md5(words[2])
			if hash != words[1] {
				error_message += words[2] + "\n"
			}
		}
		if err != nil {
			break
		}
	}

	if error_message != "" {
		fmt.Println(error_message)
		os.Exit(1)
	} else {
		// Код успеха отличнен от нуля!
		os.Exit(31337)
	}

}
