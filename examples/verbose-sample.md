# todo-cli

## Introduction

Welcome to todo-cli! todo-cli is a command line tool, which is to say a tool that you run from your terminal, that helps you to keep track of the things that you need to do. It is important to note that todo-cli is, at its core, a simple tool for managing a list of tasks. In other words, it lets you add tasks, list tasks, and complete tasks, all from the command line. As a matter of fact, the main purpose of todo-cli is to make managing tasks easy.

## Background

On Monday we decided that the project needed a README. On Tuesday we discussed what the README should contain, and we agreed that it should contain installation instructions and usage instructions. On Wednesday we wrote a first draft of the installation instructions. On Thursday we reviewed the draft and decided to rewrite part of it. On Friday we merged the rewritten version, and at that point we considered the README to be in a reasonably good state for the time being.

## Installation

To install todo-cli, you will need to have Python 3.9 or newer installed on your computer. It is worth mentioning that todo-cli does not work with older versions of Python. In order to install it, you should run `pip install todo-cli` in your terminal. Please note that you need Python 3.9 or newer, as mentioned above. After the installation has finished, you can verify that it worked by running `todo --version`, which will print the version number of todo-cli that you have installed.

## Configuration

todo-cli stores its settings in a configuration file named `todo.toml`, which lives in your home directory. It is important to note that this file may contain your sync token. For this reason, you should never commit the config file to version control. Again, to be clear: never commit the config file. If you do commit it by accident, rotate your sync token right away. You can set the default list in the configuration file, and you can also set the date format, which defaults to ISO 8601 (year-month-day).

## Usage

There are several things you can do with todo-cli. Basically, there are four main commands. Each of these is described in more detail below.

### Adding a task

To add a task, use the `add` command. For example, `todo add "buy milk"` will add a task called "buy milk" to your list. It should be noted that the task text needs to be wrapped in quotes if it contains spaces. In other words, if the task has more than one word, put quotes around it.

### Listing tasks

To list your tasks, use the `list` command. For example, `todo list` will show all of the tasks that are currently on your list. As a matter of fact, the `list` command is probably the command you will use most often, since it shows you everything that you have to do.

### Completing a task

To complete a task, use the `done` command followed by the number of the task. For example, `todo done 3` marks task number 3 as done. Please remember that the number of a task is the number that is shown next to it when you run `todo list`.

### Removing a task

To remove a task, use the `rm` command followed by the number of the task. For example, `todo rm 3` removes task number 3. It is worth noting that removing a task is different from completing a task: a completed task is kept in the history, while a removed task is gone for good.

## Frequently asked questions

**Can I use todo-cli with older versions of Python?** No. As mentioned in the installation section, you need Python 3.9 or newer.

**Where is my configuration stored?** In the file `todo.toml` in your home directory, as described in the configuration section.

**Should I commit my configuration?** No. As explained above, you should never commit the config file, because it can contain your sync token.

## Conclusion

In conclusion, todo-cli is a simple tool that helps you to manage your tasks from the command line. We hope that you find it useful, and we hope that this README has been helpful in explaining how to install it, how to configure it, and how to use it. Thank you for reading, and happy task managing!
