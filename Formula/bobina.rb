class Bobina < Formula
  include Language::Python::Virtualenv

  desc "Print Markdown on thermal roll printers"
  homepage "https://github.com/rafaelbressan/bobina"
  url "https://files.pythonhosted.org/packages/f3/c8/774d361193d3043cdb00e9830052f51f30163270afe54de27af4f47b108d/bobina-0.1.1.tar.gz"
  sha256 "e73b9c081e72f181df87a890021d2ccb91e96055c9b819c0ebe44a58b5e8b0ee"
  license "MIT"

  depends_on "libyaml"
  depends_on "pillow"
  depends_on "python@3.14"

  resource "babel" do
    url "https://files.pythonhosted.org/packages/7d/b2/51899539b6ceeeb420d40ed3cd4b7a40519404f9baf3d4ac99dc413a834b/babel-2.18.0.tar.gz"
    sha256 "b80b99a14bd085fcacfa15c9165f651fbb3406e66cc603abf11c5750937c992d"
  end

  resource "fonttools" do
    url "https://files.pythonhosted.org/packages/0c/b5/672312ae80ce8b8eb9779c56052a24c8f36652aa7293a1a420553bcf03e5/fonttools-4.68.0.tar.gz"
    sha256 "73294e233070f71e2b3653b6bd8564af676d57f26d075761fb06d1ab2e4a7a5d"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/df/bf/f7da0350254c0ed7c72f3e33cef02e048281fec7ecec5f032d4aac52226b/jinja2-3.1.6.tar.gz"
    sha256 "0137fb05990d35f1275a587e9aee6d56da821fc83491a0fb838183be43f66d6d"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/06/ff/7841249c247aa650a76b9ee4bbaeae59370dc8bfd2f6c01f3630c35eb134/markdown_it_py-4.2.0.tar.gz"
    sha256 "04a21681d6fbb623de53f6f364d352309d4094dd4194040a10fd51833e418d49"
  end

  resource "markupsafe" do
    url "https://files.pythonhosted.org/packages/38/9b/e422a865e1d5d57d0e509b4e0bf1c1a70a7f6382c29a5aa428df994c8bc8/markupsafe-3.0.4.tar.gz"
    sha256 "2e9ad7dd851bf45fab9f75cbff4cb493fee9979e8d8c7c9c3ee119022518edd6"
  end

  resource "mdit-py-plugins" do
    url "https://files.pythonhosted.org/packages/59/fc/f8d0863f8862f25602c0404d75568e89fb6b4109804645e5cdfb1be5cf56/mdit_py_plugins-0.6.1.tar.gz"
    sha256 "a2bca0f039f39dbd35fb74ae1b5f998608c437463371f0ff7f49a19a17a114d0"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end

  resource "pdf417gen" do
    url "https://files.pythonhosted.org/packages/92/77/d7cac091ffda16c7c6adddcb44cf5e46e2fc32f3b30b0c902b75a88f5a31/pdf417gen-0.8.1.tar.gz"
    sha256 "0bd42ed67af5e5f681d4202de6065a359c9b43a8790ff534f5f0490b9516893d"
  end

  resource "ppf-datamatrix" do
    url "https://files.pythonhosted.org/packages/f7/fd/9bbe3632d509ee4954c275850a6adb2b209725bc5ba1c2015bba06ea4e18/ppf-datamatrix-0.2.tar.gz"
    sha256 "8f034d9c90e408f60f8b10a273baab81014c9a81c983dc1ebdc31d4ca5ac5582"
  end

  resource "python-barcode" do
    url "https://files.pythonhosted.org/packages/0e/f2/4c0b07f100e1e184ba682021322c336bbba6aa7adfabd2616f70eff917d9/python_barcode-0.16.1.tar.gz"
    sha256 "665ed09516b0088b5593061c5ac8662caa0b08d56bdad328388b1cab39939ac5"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  resource "segno" do
    url "https://files.pythonhosted.org/packages/1c/2e/b396f750c53f570055bf5a9fc1ace09bed2dff013c73b7afec5702a581ba/segno-1.6.6.tar.gz"
    sha256 "e60933afc4b52137d323a4434c8340e0ce1e58cec71439e46680d4db188f11b3"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/bobina --version")
    assert_match "\"problems\"", shell_output("#{bin}/bobina check '# hello from brew test' --json")
    system bin/"bobina", "preview", "# hello from brew test", "-o", testpath/"hello.png"
    assert_path_exists testpath/"hello.png"
  end
end
