function setupMenu() {
    const menuToggle = document.getElementById("menu-toggle");
    const menu = document.getElementById("menu");

    if (!menuToggle || !menu) return;

    const menuItems = menu.querySelectorAll('li');

    /* En pantallas grandes submenú se abre con clic en <li>
    if (window.innerWidth > 1600) {
        menuItems.forEach(item => {
            const submenu = item.querySelector('ul.submenu');
            if (submenu) {
                item.addEventListener('click', function (event) {
                    event.stopPropagation();
                    submenu.classList.toggle('show');
                });
            }
        });

        menuItems.forEach(item => {
            const submenu = item.querySelector('ul.submenu');
            if (submenu) {
                submenu.addEventListener('mouseleave', () => {
                    submenu.classList.remove('show');
                });
            }
        });
    }*/

    // Botón de hamburguesa
    menuToggle.addEventListener("click", function () {
        menu.classList.toggle("show");
    });

    // Cierra menú al hacer clic 
    document.addEventListener("click", function (event) {
        if (!event.target.closest("#menu") && !event.target.closest("#menu-toggle")) {
            menu.classList.remove("show");
        }
    });

    /* Cierra submenús al hacer clic en enlaces*/
    menu.querySelectorAll('ul.submenu a').forEach(link => {
        link.addEventListener('click', function () {
            let parent = this.parentElement;
            while (parent && parent !== menu) {
                if (parent.classList.contains('submenu')) {
                    parent.classList.remove('show');
                }
                parent = parent.parentElement;
            }
            menu.classList.remove("show");
        });
    });
 
    if (window.innerWidth <= 1600) {
        const toggles = menu.querySelectorAll('.submenu-toggle');
        toggles.forEach(toggle => {
            toggle.addEventListener('click', function (e) {
                e.stopPropagation();
                const submenu = this.nextElementSibling;
                submenu.classList.toggle('show');
            });
        });
    }
    
    //Cerrar menú al hacer clic en cualquier enlace 
    if (window.innerWidth <= 1600) {
        const allLinks = menu.querySelectorAll('a');
        allLinks.forEach(link => {
            link.addEventListener('click', () => {
                menu.classList.remove('show');
            });
        });
    }

}
