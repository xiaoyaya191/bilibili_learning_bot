import main as main_module


def test_run_cli_handles_keyboard_interrupt_without_traceback(monkeypatch, capsys):
    def interrupted_main():
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "main", interrupted_main)
    main_module.run_cli()

    output = capsys.readouterr().out
    assert "已取消，程序已退出" in output
    assert "Traceback" not in output
