// SightOps - instalador do agente de inventario Windows (interface grafica).
//
// O .exe e o mesmo para todos os clientes. O servidor (GET
// /api/windows/agent-exe) cola no FIM do arquivo o script do agente ja com o
// endereco e a chave daquele cliente:
//
//   [exe][cliente UTF-8 '\n' script UTF-8][int32 tamanho][8 bytes "SOPSAG01"]
//
// A janela pede site e setor, e roda o script como Administrador (o manifesto
// pede elevacao): ele envia o inventario, se copia para ProgramData e cria a
// tarefa que reenvia a cada 15 min. Antes, o operador tinha de abrir o
// PowerShell como admin e passar parametros -- e esquecia, e o computador ficava
// "sem contato".
//
// Compilar: tools/agente-windows/compilar.ps1 (csc do .NET Framework 4, que ja
// vem no Windows; C# 5, sem interpolacao de string).
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("SightOps - Agente de inventario")]
[assembly: System.Reflection.AssemblyProduct("SightOps")]
[assembly: System.Reflection.AssemblyVersion("2.1.0.0")]

namespace SightOps
{
    static class Programa
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            string cliente, script;
            if (!LerConfiguracao(out cliente, out script))
            {
                MessageBox.Show(
                    "Este instalador nao tem a configuracao do cliente.\n\n" +
                    "Baixe o agente pelo SightOps: Inventario > Computadores > Instalar agente.",
                    "SightOps", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            Application.Run(new Janela(cliente, script));
        }

        static bool LerConfiguracao(out string cliente, out string script)
        {
            cliente = ""; script = "";
            try
            {
                byte[] tudo = File.ReadAllBytes(Application.ExecutablePath);
                if (tudo.Length < 12) return false;
                string marca = Encoding.ASCII.GetString(tudo, tudo.Length - 8, 8);
                if (marca != "SOPSAG01") return false;
                int tam = BitConverter.ToInt32(tudo, tudo.Length - 12);
                if (tam <= 0 || tam > tudo.Length - 12) return false;
                string dados = Encoding.UTF8.GetString(tudo, tudo.Length - 12 - tam, tam);
                int nl = dados.IndexOf('\n');
                if (nl < 0) return false;
                cliente = dados.Substring(0, nl).Trim();
                script = dados.Substring(nl + 1);
                return script.Length > 100;
            }
            catch { return false; }
        }
    }

    class Janela : Form
    {
        readonly string script;
        readonly TextBox txtSite = new TextBox();
        readonly TextBox txtSetor = new TextBox();
        readonly CheckBox chkAnyDesk = new CheckBox();
        readonly Button btn = new Button();
        readonly TextBox log = new TextBox();
        readonly Label status = new Label();
        bool terminou;

        static readonly Color Verde = Color.FromArgb(8, 127, 91);
        static readonly Color Escuro = Color.FromArgb(19, 37, 45);
        static readonly Color Cinza = Color.FromArgb(79, 93, 102);

        public Janela(string cliente, string script)
        {
            this.script = script;
            Text = "SightOps - Agente de inventario";
            Font = new Font("Segoe UI", 10F);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(560, 520);
            BackColor = Color.White;

            var topo = new Panel { Dock = DockStyle.Top, Height = 78, BackColor = Escuro };
            var t1 = new Label { Text = "SightOps", ForeColor = Color.White, Font = new Font("Segoe UI Semibold", 15F),
                                 Location = new Point(22, 12), AutoSize = true };
            var t2 = new Label { Text = string.IsNullOrEmpty(cliente) ? "Agente de inventario" : "Agente de inventario - " + cliente,
                                 ForeColor = Color.FromArgb(190, 210, 216), Location = new Point(24, 46), AutoSize = true };
            topo.Controls.Add(t1); topo.Controls.Add(t2);
            Controls.Add(topo);

            int y = 96;
            var intro = new Label { Text = "Este computador vai aparecer no SightOps com hardware, seguranca e AnyDesk, " +
                                           "e sera atualizado sozinho a cada 15 minutos.",
                                    ForeColor = Cinza, Location = new Point(22, y), Size = new Size(516, 42) };
            Controls.Add(intro);
            y += 50;

            Controls.Add(new Label { Text = "Site / unidade", Location = new Point(22, y), AutoSize = true });
            txtSite.Location = new Point(22, y + 22); txtSite.Size = new Size(516, 27);
            Controls.Add(txtSite);
            y += 62;
            Controls.Add(new Label { Text = "Setor", Location = new Point(22, y), AutoSize = true });
            txtSetor.Location = new Point(22, y + 22); txtSetor.Size = new Size(516, 27);
            Controls.Add(txtSetor);
            y += 62;

            chkAnyDesk.Text = "Instalar o AnyDesk se este computador ainda nao tiver";
            chkAnyDesk.Checked = true;
            chkAnyDesk.Location = new Point(22, y); chkAnyDesk.AutoSize = true;
            Controls.Add(chkAnyDesk);
            y += 38;

            btn.Text = "Instalar";
            btn.Location = new Point(22, y); btn.Size = new Size(516, 42);
            btn.BackColor = Verde; btn.ForeColor = Color.White; btn.FlatStyle = FlatStyle.Flat;
            btn.FlatAppearance.BorderSize = 0;
            btn.Font = new Font("Segoe UI Semibold", 11F);
            btn.Click += Clicar;
            Controls.Add(btn);
            AcceptButton = btn;
            y += 52;

            status.Location = new Point(22, y); status.Size = new Size(516, 22); status.ForeColor = Cinza;
            Controls.Add(status);
            y += 26;

            log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical;
            log.Location = new Point(22, y); log.Size = new Size(516, ClientSize.Height - y - 16);
            log.Font = new Font("Consolas", 9F); log.BackColor = Color.FromArgb(246, 248, 249);
            Controls.Add(log);

            CarregarSalvo();
        }

        // Reinstalar no mesmo PC traz o site/setor da vez anterior.
        void CarregarSalvo()
        {
            try
            {
                string cfg = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), @"SightOps\agente.json");
                if (!File.Exists(cfg)) return;
                string j = File.ReadAllText(cfg);
                Match s = Regex.Match(j, "\"site\"\\s*:\\s*\"([^\"]*)\"");
                Match t = Regex.Match(j, "\"setor\"\\s*:\\s*\"([^\"]*)\"");
                if (s.Success) txtSite.Text = s.Groups[1].Value;
                if (t.Success) txtSetor.Text = t.Groups[1].Value;
            }
            catch { }
        }

        static string Limpo(string v)
        {
            // Vai para a linha de comando do PowerShell: sem aspas, sem caracteres de
            // controle e sem barra invertida -- "Sede\" viraria \" (aspa literal) e
            // engoliria o -Setor seguinte.
            return Regex.Replace(v ?? "", "[\"`$\\\\\\r\\n\\t]", "").Trim();
        }

        void Clicar(object sender, EventArgs e)
        {
            if (terminou) { Close(); return; }
            if (Limpo(txtSite.Text).Length == 0)
            {
                status.ForeColor = Color.FromArgb(201, 42, 42);
                status.Text = "Informe o site ou unidade deste computador.";
                txtSite.Focus();
                return;
            }
            btn.Enabled = false; txtSite.Enabled = false; txtSetor.Enabled = false; chkAnyDesk.Enabled = false;
            btn.Text = "Instalando...";
            status.ForeColor = Cinza;
            status.Text = "Coletando o inventario e enviando ao SightOps. Pode levar ate 1 minuto.";
            log.Clear();

            string arq = Path.Combine(Path.GetTempPath(), "sightops-agente-" + Guid.NewGuid().ToString("N") + ".ps1");
            File.WriteAllText(arq, script, new UTF8Encoding(true));
            string args = "-NoProfile -ExecutionPolicy Bypass -File \"" + arq + "\" -Silencioso" +
                          " -Site \"" + Limpo(txtSite.Text) + "\" -Setor \"" + Limpo(txtSetor.Text) + "\"" +
                          (chkAnyDesk.Checked ? " -InstalarAnyDesk" : "");
            var psi = new ProcessStartInfo("powershell.exe", args)
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            var saida = new StringBuilder();
            DataReceivedEventHandler escrever = (s, a) =>
            {
                if (a.Data == null) return;
                lock (saida) saida.AppendLine(a.Data);
                BeginInvoke((Action)(() => log.AppendText(a.Data + Environment.NewLine)));
            };
            proc.OutputDataReceived += escrever;
            proc.ErrorDataReceived += escrever;
            proc.Exited += (s, a) => BeginInvoke((Action)(() =>
            {
                try { File.Delete(arq); } catch { }
                string tudo; lock (saida) tudo = saida.ToString();
                Concluir(proc.ExitCode == 0 && tudo.Contains("Inventario enviado com sucesso"),
                         tudo.Contains("Tarefa 'SightOps Inventario' criada"));
            }));
            try
            {
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
            }
            catch (Exception ex)
            {
                log.AppendText("Nao consegui iniciar o PowerShell: " + ex.Message + Environment.NewLine);
                Concluir(false, false);
            }
        }

        void Concluir(bool enviado, bool agendado)
        {
            if (enviado && agendado)
            {
                status.ForeColor = Verde;
                status.Text = "Pronto! O computador ja aparece no SightOps e se atualiza a cada 15 min.";
                btn.Text = "Fechar";
                btn.Enabled = true;
                terminou = true;
                return;
            }
            status.ForeColor = Color.FromArgb(201, 42, 42);
            status.Text = enviado
                ? "Inventario enviado, mas a tarefa agendada nao foi criada. Veja o registro abaixo."
                : "Nao deu certo. Veja o registro abaixo e tente de novo.";
            btn.Text = "Tentar de novo";
            btn.Enabled = true; txtSite.Enabled = true; txtSetor.Enabled = true; chkAnyDesk.Enabled = true;
        }
    }
}
